from datetime import datetime
import logging

log = logging.getLogger(__name__)

import numpy
from box import BoundingBox
from mclevelbase import exhaust
import materials
import biome_types
from entity import Entity, TileEntity
from copy import deepcopy


def convertBlocks(destLevel, sourceLevel, blocks, blockData):
    return materials.convertBlocks(destLevel.materials, sourceLevel.materials, blocks, blockData)


def convertBiomes(destLevel, sourceLevel, biomes):
    return biome_types.convertBiomes(destLevel.biomeTypes, sourceLevel.biomeTypes, biomes)


def sourceMaskFunc(blocksToCopy):
    if blocksToCopy is not None:
        maskLen = max(blocksToCopy) + 1
        # plus 1 to have an extra entry at the end that is always zero
        typemask = numpy.zeros(maskLen + 1, dtype="bool")
        typemask[blocksToCopy] = 1

        def maskedSourceMask(sourceBlocks):
            return typemask[numpy.minimum(sourceBlocks, maskLen)]

        return maskedSourceMask

    def unmaskedSourceMask(_sourceBlocks):
        return slice(None, None)

    return unmaskedSourceMask


def adjustCopyParameters(destLevel, sourceLevel, sourceBox, destinationPoint):
    log.debug(u"Asked to copy {} blocks \n\tfrom {} in {}\n\tto {} in {}".format(
        sourceBox.volume, sourceBox, sourceLevel, destinationPoint, destLevel))
    if destLevel.Width == 0:
        return sourceBox, destinationPoint

    destBox = BoundingBox(destinationPoint, sourceBox.size)
    actualDestBox = destBox.intersect(destLevel.bounds)

    actualSourceBox = BoundingBox(sourceBox.origin + actualDestBox.origin - destBox.origin, destBox.size)
    actualDestPoint = actualDestBox.origin

    return actualSourceBox, actualDestPoint


def _getBiomeCopyViews(destChunk, sourceChunk, destSlices, sourceSlices):
    destBiomes = destChunk.Biomes
    sourceBiomes = sourceChunk.Biomes

    destScale = destChunk.biomesScale
    # adjust the start and stop of destSlices to match destScale
    destBiomesSlices = tuple([slice(
        s.start // destScale,
        (s.stop + (destScale - 1)) // destScale,
        s.step) for s in destSlices[:len(destBiomes.shape)]])

    sourceScaleInv = 1.0 / sourceChunk.biomesScale
    # meshgrid for expanding sourceBiomes to full width if needed
    sourceGrid = numpy.mgrid[tuple(
        [slice(None, s, sourceScaleInv) for s in sourceBiomes.shape])].astype("uint")
    # adjust the step of sourceSlices to match destScale
    sourceBiomesSlices = tuple([slice(s.start, s.stop, destScale)
        for s in sourceSlices[:len(sourceBiomes.shape)]])

    sourceBiomes = sourceBiomes[tuple(sourceGrid)][sourceBiomesSlices]
    destBiomes = destBiomes[destBiomesSlices]
    if len(destBiomes.shape) == 3 and len(sourceBiomes.shape) == 2:
        # so sourceBiomes is broadcasted along the y axis correctly
        destBiomes = numpy.moveaxis(destBiomes, 2, 0)
    elif len(destBiomes.shape) == 2 and len(sourceBiomes.shape) == 3:
        # only use the bottom y block from sourceBiomes
        sourceBiomes = sourceBiomes[:, :, 0]

    return destBiomes, sourceBiomes


def copyBlocksFromIter(destLevel, sourceLevel, sourceBox, destinationPoint, blocksToCopy=None, entities=True,
                       create=False, biomes=False, tileTicks=True, staticCommands=False, moveSpawnerPos=False, regenerateUUID=False, first=None, cancelCommandBlockOffset=False):
    """ copy blocks between two infinite levels by looping through the
    destination's chunks. make a sub-box of the source level for each chunk
    and copy block and entities in the sub box to the dest chunk."""

    (lx, ly, lz) = sourceBox.size

    sourceBox, destinationPoint = adjustCopyParameters(destLevel, sourceLevel, sourceBox, destinationPoint)
    # needs work xxx
    log.info(u"Copying {0} blocks from {1} to {2}".format(ly * lz * lx, sourceBox, destinationPoint))
    startTime = datetime.now()

    destBox = BoundingBox(destinationPoint, sourceBox.size)
    chunkCount = destBox.chunkCount
    i = 0
    e = 0
    t = 0
    tt = 0
    sourceMask = sourceMaskFunc(blocksToCopy)

    copyOffset = [d - s for s, d in zip(sourceBox.origin, destinationPoint)]

    # Visit each chunk in the destination area.
    # Get the region of the source area corresponding to that chunk
    #   Visit each chunk of the region of the source area
    #     Get the slices of the destination chunk
    #     Get the slices of the source chunk
    #     Copy blocks and data

    for destCpos in destBox.chunkPositions:
        cx, cz = destCpos

        destChunkBox = BoundingBox((cx << 4, destLevel.minY, cz << 4), (16, destLevel.Height, 16)).intersect(destBox)
        destChunkBoxInSourceLevel = BoundingBox([d - o for o, d in zip(copyOffset, destChunkBox.origin)],
                                                destChunkBox.size)

        if not destLevel.containsChunk(*destCpos):
            if create and any(sourceLevel.containsChunk(*c) for c in destChunkBoxInSourceLevel.chunkPositions):
                # Only create chunks in the destination level if the source level has chunks covering them.
                destLevel.createChunk(*destCpos)
            else:
                continue

        destChunk = destLevel.getChunk(*destCpos)

        i += 1
        yield (i, chunkCount)
        if i % 100 == 0:
            log.info("Chunk {0}...".format(i))

        for srcCpos in destChunkBoxInSourceLevel.chunkPositions:
            if not sourceLevel.containsChunk(*srcCpos):
                continue

            sourceChunk = sourceLevel.getChunk(*srcCpos)

            sourceChunkBox, sourceSlices = sourceChunk.getChunkSlicesForBox(destChunkBoxInSourceLevel)
            if sourceChunkBox.volume == 0:
                continue

            sourceChunkBoxInDestLevel = BoundingBox([d + o for o, d in zip(copyOffset, sourceChunkBox.origin)],
                                                    sourceChunkBox.size)

            _, destSlices = destChunk.getChunkSlicesForBox(sourceChunkBoxInDestLevel)

            sourceBlocks = sourceChunk.Blocks[sourceSlices]
            sourceData = sourceChunk.Data[sourceSlices]

            mask = sourceMask(sourceBlocks)
            convertedSourceBlocks, convertedSourceData = convertBlocks(destLevel, sourceLevel, sourceBlocks, sourceData)

            destChunk.Blocks[destSlices][mask] = convertedSourceBlocks[mask]
            if convertedSourceData is not None:
                destChunk.Data[destSlices][mask] = convertedSourceData[mask]

            if entities:
                ents = sourceChunk.getEntitiesInBox(destChunkBoxInSourceLevel)
                e += len(ents)
                for entityTag in ents:
                    eTag = destLevel.entityTypes.copyWithOffset(entityTag, copyOffset, regenerateUUID)
                    destLevel.addEntity(eTag)

            def copy(p):
                return p in sourceChunkBoxInDestLevel and (blocksToCopy is None or mask[
                    int(p[0] - sourceChunkBoxInDestLevel.minx),
                    int(p[2] - sourceChunkBoxInDestLevel.minz),
                    int(p[1] - sourceChunkBoxInDestLevel.miny),
                ])

            destChunk.removeTileEntities(copy)

            tileEntities = sourceChunk.getTileEntitiesInBox(destChunkBoxInSourceLevel)
            t += len(tileEntities)
            for tileEntityTag in tileEntities:
                if cancelCommandBlockOffset:
                    first = None
                    staticCommands = False
                    moveSpawnerPos = False
                eTag = destLevel.tileEntityTypes.copyWithOffset(tileEntityTag, copyOffset, toSchematic=first, moveCommandPos=staticCommands, moveSpawnerPos=moveSpawnerPos)
                destLevel.addTileEntity(eTag)

            destChunk.removeTileTicks(copy)

            if tileTicks:
                tileTicksList = sourceChunk.getTileTicksInBox(destChunkBoxInSourceLevel)
                tt += len(tileTicksList)
                for tileTick in tileTicksList:
                    eTag = deepcopy(tileTick)
                    eTag['x'].value = tileTick['x'].value + copyOffset[0]
                    eTag['y'].value = tileTick['y'].value + copyOffset[1]
                    eTag['z'].value = tileTick['z'].value + copyOffset[2]
                    destLevel.addTileTick(eTag)

            if biomes and hasattr(destChunk, 'Biomes') and hasattr(sourceChunk, 'Biomes'):
                destBiomes, sourceBiomes = _getBiomeCopyViews(destChunk, sourceChunk, destSlices, sourceSlices)
                destBiomes[:] = convertBiomes(destLevel, sourceLevel, sourceBiomes)

        destChunk.chunkChanged()

    log.info("Duration: {0}".format(datetime.now() - startTime))
    log.info("Copied {0} entities and {1} tile entities and {2} tile ticks".format(e, t, tt))


def copyBlocksFrom(destLevel, sourceLevel, sourceBox, destinationPoint, blocksToCopy=None, entities=True, create=False,
                   biomes=False, tileTicks=True, staticCommands=False, moveSpawnerPos=False, regenerateUUID=False, first=None, cancelCommandBlockOffset=False):
    return exhaust(
        copyBlocksFromIter(destLevel, sourceLevel, sourceBox, destinationPoint,
            blocksToCopy=blocksToCopy, entities=entities, create=create,
            biomes=biomes, tileTicks=tileTicks, staticCommands=staticCommands,
            moveSpawnerPos=moveSpawnerPos, regenerateUUID=regenerateUUID,
            first=first, cancelCommandBlockOffset=cancelCommandBlockOffset))
