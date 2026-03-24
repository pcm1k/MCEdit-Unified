import logging
import materials

log = logging.getLogger(__name__)

import numpy

from mclevelbase import exhaust
from box import BoundingBox
from entity import TileEntity


def _blockReplaceTable(blocksToReplace):
    blocktable = materials.UnlimitedBlockTable.fromBlocks(blocksToReplace, "bool")
    for b in blocksToReplace:
        blocktable[b.ID, b.blockData] = True
    return blocktable


def blockReplaceFunc(blocksToReplace):
    blocktable = _blockReplaceTable(blocksToReplace)

    def replaceFunc(blocks, data):
        mask = numpy.zeros(blocks.shape, dtype="bool")
        belowLimit, dataIndex = blocktable.indexChecked(blocks, data)
        mask[belowLimit] = blocktable.table[dataIndex]
        return mask

    return replaceFunc


def fillBlocks(level, box, blockInfo, blocksToReplace=(), noData=False):
    return exhaust(level.fillBlocksIter(box, blockInfo, blocksToReplace, noData=noData))


def fillBlocksIter(level, box, blockInfo, blocksToReplace=(), noData=False):
    if box is None:
        chunkIterator = level.getAllChunkSlices()
        box = level.bounds
    else:
        chunkIterator = level.getChunkSlices(box)

    log.info("Replacing {0} with {1}".format(blocksToReplace, blockInfo))

    changesLighting = True
    replaceFunc = None
    if len(blocksToReplace):
        replaceFunc = blockReplaceFunc(blocksToReplace)

        newAbsorption = level.materials.lightAbsorption[blockInfo.ID]
        oldAbsorptions = [level.materials.lightAbsorption[b.ID] for b in blocksToReplace]
        changesLighting = False
        for a in oldAbsorptions:
            if a != newAbsorption:
                changesLighting = True

        newEmission = level.materials.lightEmission[blockInfo.ID]
        oldEmissions = [level.materials.lightEmission[b.ID] for b in blocksToReplace]
        for a in oldEmissions:
            if a != newEmission:
                changesLighting = True

    tileEntity = level.tileEntityTypes.stringNames.get(blockInfo.stringID)

    blocksIdToReplace = [block.ID for block in blocksToReplace]

    blocksList = []
    append = blocksList.append
    if tileEntity and box is not None:
        for (boxX, boxY, boxZ) in box.positions:
            if replaceFunc is None or level.blockAt(boxX, boxY, boxZ) in blocksIdToReplace:
                tileEntityObject = level.tileEntityTypes.Create(tileEntity)
                TileEntity.setpos(tileEntityObject, (boxX, boxY, boxZ))
                append(tileEntityObject)

    i = 0
    skipped = 0
    replaced = 0

    for (chunk, slices, point) in chunkIterator:
        i += 1
        if i % 100 == 0:
            log.info(u"Chunk {0}...".format(i))
        yield i, box.chunkCount

        blocks = chunk.Blocks[slices]
        data = chunk.Data[slices]

        needsLighting = changesLighting

        if replaceFunc is not None:
            mask = replaceFunc(blocks, data)

            blockCount = mask.sum()
            replaced += blockCount

            # don't waste time relighting and copying if the mask is empty
            if blockCount:
                blocks[mask] = blockInfo.ID
                if not noData:
                    data[mask] = blockInfo.blockData
                else:
                    # try to avoid invalid blocks
                    # pcm1k TODO - maybe the noData option should just not be allowed in post-flattening versions?
                    if blockInfo.blockData >= materials.data_limit:
                        blockInfo = level.materials.blockWithID(blockInfo.ID, None)
                        data[mask] = blockInfo.blockData
                    else:
                        aboveLimit = mask & (data >= materials.data_limit)
                        if aboveLimit.any():
                            blockInfo = level.materials.blockWithID(blockInfo.ID, None)
                            data[aboveLimit] = blockInfo.blockData
            else:
                skipped += 1
                needsLighting = False

            def include(tileEntity):
                p = TileEntity.pos(tileEntity)
                x, y, z = map(lambda a, b, c: (a - b) - c, p, point, box.origin)
                return not ((p in box) and mask[x, z, y])

            chunk.TileEntities[:] = filter(include, chunk.TileEntities)

        else:
            blocks[:] = blockInfo.ID
            if not noData:
                data[:] = blockInfo.blockData
            else:
                # try to avoid invalid blocks
                # pcm1k TODO - maybe the noData option should just not be allowed in post-flattening versions?
                if blockInfo.blockData >= materials.data_limit:
                    blockInfo = level.materials.blockWithID(blockInfo.ID, None)
                    data[:] = blockInfo.blockData
                else:
                    aboveLimit = data >= materials.data_limit
                    if aboveLimit.any():
                        blockInfo = level.materials.blockWithID(blockInfo.ID, None)
                        data[aboveLimit] = blockInfo.blockData
            chunk.removeTileEntitiesInBox(box)

        chunkBounds = chunk.bounds
        smallBoxSize = (1, 1, 1)
        tileEntitiesToEdit = [t for t in blocksList if chunkBounds.intersect(BoundingBox(TileEntity.pos(t), smallBoxSize)).volume > 0]

        for tileEntityObject in tileEntitiesToEdit:
            chunk.addTileEntity(tileEntityObject)
            blocksList.remove(tileEntityObject)

        chunk.chunkChanged(needsLighting)

    if len(blocksToReplace):
        log.info(u"Replace: Skipped {0} chunks, replaced {1} blocks".format(skipped, replaced))
