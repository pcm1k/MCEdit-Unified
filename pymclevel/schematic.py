"""
Created on Jul 22, 2011

@author: Rio
"""
import atexit
from contextlib import closing
import os
import shutil
import zipfile
from logging import getLogger

import blockrotation
from box import BoundingBox
import infiniteworld
from level import MCLevel, EntityLevel, GAME_PLATFORM_SCHEMATIC
from materials import alphaMaterials, MCMaterials, namedMaterials, BlockstateAPI, getMaterials
from mclevelbase import exhaust
from id_definitions import get_defs_ids, PLATFORM_ALPHA, VERSION_LATEST
import nbt
from numpy import array, ndenumerate, ndindex, resize, swapaxes, zeros
import math
import copy
from collections import defaultdict

log = getLogger(__name__)

__all__ = ['MCSchematic', 'INVEditChest', 'StructureNBT']

DEBUG = True


class MCSchematic(EntityLevel):
    _gamePlatform = GAME_PLATFORM_SCHEMATIC

    def __init__(self, shape=None, root_tag=None, filename=None, mats='Alpha'):
        """ shape is (x,y,z) for a new level's shape.  if none, takes
        root_tag as a TAG_Compound for an existing schematic file.  if
        none, tries to read the tag from filename.  if none, results
        are undefined. materials can be a MCMaterials instance, or one of
        "Classic", "Alpha", "Pocket" to indicate allowable blocks. The default
        is Alpha.

        block coordinate order in the file is y,z,x to use the same code as classic/indev levels.
        in hindsight, this was a completely arbitrary decision.

        the Entities and TileEntities are nbt.TAG_List objects containing TAG_Compounds.
        this makes it easy to copy entities without knowing about their insides.

        rotateLeft swaps the axes of the different arrays.  because of this, the Width, Height, and Length
        reflect the current dimensions of the schematic rather than the ones specified in the NBT structure.
        I'm not sure what happens when I try to re-save a rotated schematic.
        """

        if DEBUG: log.debug(u"Creating schematic.")
        if filename:
            if DEBUG: log.debug(u"Using %s"%filename)
            self.filename = filename
            if None is root_tag and os.path.exists(filename):
                root_tag = nbt.load(filename)
                if DEBUG: log.debug(u"%s loaded."%filename)
        else:
            self.filename = None

        if root_tag:
            self._load(root_tag, mats)
        else:
            self._create(shape, mats)

    def _load(self, root_tag, mats="Alpha"):
        self.root_tag = root_tag
        if DEBUG: log.debug(u"Processing materials.")
        if "Materials" in root_tag:
            self.materials = namedMaterials[self.Materials]
        else:
            if mats in namedMaterials:
                if DEBUG: log.debug(u"Using named materials.")
                self.materials = mats = namedMaterials[mats]
            else:
                assert (isinstance(mats, MCMaterials))
                self.materials = mats
            root_tag["Materials"] = nbt.TAG_String(mats.name)

        if DEBUG: log.debug(u"Processing size.")
        w = root_tag["Width"].value
        l = root_tag["Length"].value
        h = root_tag["Height"].value

        if DEBUG: log.debug(u"Reshaping blocks.")
        self._Blocks = root_tag.pop("Blocks").value.astype("uint16").reshape(h, l, w)
        if "AddBlocks" in root_tag:
            if DEBUG: log.debug(u"Processing AddBlocks.")
            # Use WorldEdit's "AddBlocks" array to load and store the 4 high bits of a block ID.
            # Unlike Minecraft's NibbleArrays, this array stores the first block's bits in the
            # 4 high bits of the first byte.

            size = (h * l * w)

            # If odd, add one to the size to make sure the adjacent slices line up.
            add = zeros(size + (size & 1), dtype="uint16")

            # Fill the even bytes with data
            add[::2] = resize(root_tag.pop("AddBlocks").value, add[::2].shape)

            # Copy the low 4 bits to the odd bytes
            add[1::2] = add[::2] & 0xf

            # Shift the even bytes down
            add[::2] >>= 4

            # Shift every byte up before merging it with Blocks
            add <<= 8
            self._Blocks |= add[:size].reshape(h, l, w)

        self._Blocks = swapaxes(self._Blocks, 0, 2)
        self._Data = swapaxes(root_tag.pop("Data").value.astype("uint8").reshape(h, l, w) & 0xF, 0, 2)
#        self._Data = swapaxes(root_tag.pop("Data").value.astype("uint16").reshape(h, l, w) & 0xF, 0, 2)

        if "Biomes" in root_tag:
            if DEBUG: log.debug(u"Processing Biomes.")
            root_tag["Biomes"].value.shape = (l, w)

    def _create(self, shape, mats="Alpha"):
        if DEBUG: log.debug(u"No root tag found, creating a blank schematic.")
        assert shape is not None
        self.root_tag = root_tag = nbt.TAG_Compound(name="Schematic")
        root_tag["Height"] = nbt.TAG_Short(shape[1])
        root_tag["Length"] = nbt.TAG_Short(shape[2])
        root_tag["Width"] = nbt.TAG_Short(shape[0])

        root_tag["Entities"] = nbt.TAG_List()
        root_tag["TileEntities"] = nbt.TAG_List()
        root_tag["TileTicks"] = nbt.TAG_List()

        if mats in namedMaterials:
            if DEBUG: log.debug(u"Using named materials.")
            self.materials = mats = namedMaterials[mats]
        else:
            assert (isinstance(mats, MCMaterials))
            self.materials = mats
        root_tag["Materials"] = nbt.TAG_String(mats.name)

        self._Blocks = zeros((shape[0], shape[2], shape[1]), dtype="uint16")
        # This is made uint16 to allow old code that uses MCSchematic only to
        # manipulate stuff (in memory) to still work as expected. If it is saved
        # it will be converted to old blocks, however
        self._Data = zeros((shape[0], shape[2], shape[1]), dtype="uint16" if self.filename is None else "uint8")

        # pcm1k TODO - make this 3d and uint16 for the same reason?
        root_tag["Biomes"] = nbt.TAG_Byte_Array(zeros((shape[2], shape[0]), dtype="uint8"))

    def saveToFile(self, filename=None):
        """ save to file named filename, or use self.filename.  XXX NOT THREAD SAFE AT ALL. """
        if filename is None:
            filename = self.filename
        if filename is None:
            raise IOError, u"Attempted to save an unnamed schematic in place"

        # pcm1k TODO - actually do the conversion mentioned
        if self.materials.name == "AlphaFlat":
            raise NotImplementedError("Conversion to old blocks is currently not supported")

        self.Materials = self.materials.name

        blocksSwapped = swapaxes(self.Blocks, 0, 2)
        self.root_tag["Blocks"] = nbt.TAG_Byte_Array(blocksSwapped.astype("uint8"))

        add = blocksSwapped >> 8 & 0xF
        if add.any():
            # WorldEdit AddBlocks compatibility.
            # The first 4-bit value is stored in the high bits of the first byte.

            # Increase odd size by one to align slices.
            packed_add = zeros(add.size + (add.size & 1), dtype="uint8")
            packed_add[:add.size] = add.ravel()

            # Shift even bytes to the left
            packed_add[::2] <<= 4

            # Merge odd bytes into even bytes
            packed_add[::2] |= packed_add[1::2]

            # Save only the even bytes, now that they contain the odd bytes in their lower bits.
            packed_add = packed_add[0::2]
            self.root_tag["AddBlocks"] = nbt.TAG_Byte_Array(packed_add)

        self.root_tag["Data"] = nbt.TAG_Byte_Array(swapaxes(self.Data, 0, 2).astype("uint8") & 0xF)

        # delete "TileTicks" if it is empty
        if "TileTicks" in self.root_tag and not bool(self.TileTicks):
            del self.root_tag["TileTicks"]

        with open(filename, 'wb') as chunkfh:
            self.root_tag.save(chunkfh)

        del self.root_tag["Blocks"]
        del self.root_tag["Data"]
        self.root_tag.pop("AddBlocks", None)

    def __str__(self):
        return u"MCSchematic(shape={0}, materials={2}, filename=\"{1}\")".format(self.size, self.filename or u"",
                                                                                 self.Materials)

    # these refer to the blocks array instead of the file's height because rotation swaps the axes
    # this will have an impact later on when editing schematics instead of just importing/exporting
    @property
    def Length(self):
        return self.Blocks.shape[1]

    @property
    def Width(self):
        return self.Blocks.shape[0]

    @property
    def Height(self):
        return self.Blocks.shape[2]

    @property
    def Blocks(self):
        return self._Blocks

    @property
    def Data(self):
        return self._Data

    @property
    def Entities(self):
        return self.root_tag["Entities"]

    @property
    def TileEntities(self):
        return self.root_tag["TileEntities"]

    @property
    def TileTicks(self):
        tileTicks = self.root_tag.get("TileTicks")
        if tileTicks is None:
            self.root_tag["TileTicks"] = tileTicks = nbt.TAG_List()
        return tileTicks

    @property
    def Materials(self):
        return self.root_tag["Materials"].value

    @Materials.setter
    def Materials(self, val):
        self.root_tag["Materials"].value = val

    @property
    def Biomes(self):
        biomes = self.root_tag.get("Biomes")
        if biomes is None:
            self.root_tag["Biomes"] = biomes = nbt.TAG_Byte_Array(zeros((self.Length, self.Width), dtype="uint8"))
        return swapaxes(biomes.value, 0, 1)

    @classmethod
    def _isTagLevel(cls, root_tag):
        return root_tag.name == "Schematic"

    def _update_shape(self):
        root_tag = self.root_tag
        shape = self.Blocks.shape
        root_tag["Height"] = nbt.TAG_Short(shape[2])
        root_tag["Length"] = nbt.TAG_Short(shape[1])
        root_tag["Width"] = nbt.TAG_Short(shape[0])

    @staticmethod
    def _getPaintingFacing(entity):
        facing = entity.get("Facing")
        if facing is not None:
            return facing
        facing = entity.get("Direction")
        if facing is not None:
            return facing
        facing = entity.get("Dir")
        if facing is not None:
            # swap 0 and 2
            if facing.value == 0:
                facing.value = 2
            elif facing.value == 2:
                facing.value = 0
        return None

    def rotateLeftBlocks(self):
        """
        rotateLeft the blocks direction without their location
        """
        blockrotation.RotateLeft(self.Blocks, self.Data, mats=self.materials)

    def rotateLeft(self):
        self._Blocks = swapaxes(self._Blocks, 0, 1)[:, ::-1, :]  # x=z; z=-x
        self._Data = swapaxes(self._Data, 0, 1)[:, ::-1, :]
        if "Biomes" in self.root_tag:
            self.root_tag["Biomes"].value = swapaxes(self.root_tag["Biomes"].value, 0, 1)[::-1, :]
        self._update_shape()
        self.rotateLeftBlocks()
        self._rotateLeftEntities()

    def _rotateLeftEntities(self):
        self._fakeEntities = None

        log.info(u"Relocating entities...")
        for entity in self.Entities:
            pos = entity["Pos"]
            # The "wrong" axis length is used because of the axis swap before. It's kinda confusing...
            pos[0].value, pos[2].value = \
                pos[2].value, self.Length - pos[0].value
            if "Motion" in entity:
                motion = entity["Motion"]
                motion[0].value, motion[2].value = \
                    motion[2].value, -motion[0].value

            entity["Rotation"][0].value -= 90.0

            if "TileX" in entity and "TileZ" in entity:
                entity["TileX"].value, entity["TileZ"].value = \
                    entity["TileZ"].value, self.Length - entity["TileX"].value - 1
                facing = self._getPaintingFacing(entity)
                if facing is not None:
                    facing.value = (facing.value - 1) % 4

        for tileEntities in self.TileEntities, self.TileTicks:
            for tileEntity in tileEntities:
                if "x" not in tileEntity or "z" not in tileEntity:
                    continue
                tileEntity["x"].value, tileEntity["z"].value = \
                    tileEntity["z"].value, self.Length - tileEntity["x"].value - 1

    def rollBlocks(self):
        """
        rolls the blocks direction without the block location
        """
        blockrotation.Roll(self.Blocks, self.Data, mats=self.materials)

    def roll(self):
        self._Blocks = swapaxes(self._Blocks, 0, 2)[::-1, :, :]  # x=-y; y=x
        self._Data = swapaxes(self._Data, 0, 2)[::-1, :, :]
        self.root_tag.pop("Biomes", None)
        self._update_shape()
        self.rollBlocks()
        self._rollEntities()

    def _rollEntities(self):
        self._fakeEntities = None

        log.info(u"N/S Roll: Relocating entities...")
        for entity in self.Entities:
            pos = entity["Pos"]
            # The "wrong" axis length is used because of the axis swap before. It's kinda confusing...
            pos[0].value, pos[1].value = \
                self.Width - pos[1].value, pos[0].value
            if "Motion" in entity:
                motion = entity["Motion"]
                motion[0].value, motion[1].value = \
                    -motion[1].value, motion[0].value

            if "Rotation" in entity:
                # I think this is right
                # Although rotation isn't that important as most entities can't rotate and mobs
                # don't serialize rotation.
                rotation = entity["Rotation"]
                rotation[0].value, rotation[1].value = \
                    rotation[1].value, -rotation[0].value

            if "TileX" in entity and "TileY" in entity:
                entity["TileX"].value, entity["TileY"].value = \
                    self.Width - entity["TileY"].value - 1, entity["TileX"].value

        for tileEntities in self.TileEntities, self.TileTicks:
            for tileEntity in tileEntities:
                if "x" not in tileEntity or "z" not in tileEntity:
                    continue
                tileEntity["x"].value, tileEntity["y"].value = \
                    self.Width - tileEntity["y"].value - 1, tileEntity["x"].value

    def flipVerticalBlocks(self):
        blockrotation.FlipVertical(self.Blocks, self.Data, mats=self.materials)

    def flipVertical(self):
        self._Blocks = self._Blocks[:, :, ::-1]  # y=-y
        self._Data = self._Data[:, :, ::-1]
        self.flipVerticalBlocks()
        self._flipVerticalEntities()

    def _flipVerticalEntities(self):
        self._fakeEntities = None

        log.info(u"Vertical Flip: Relocating entities...")
        for entity in self.Entities:
            entity["Pos"][1].value = self.Height - entity["Pos"][1].value
            if "Motion" in entity:
                entity["Motion"][1].value = -entity["Motion"][1].value

            if "Rotation" in entity:
                entity["Rotation"][1].value = -entity["Rotation"][1].value

            if "TileY" in entity:
                entity["TileY"].value = self.Height - entity["TileY"].value - 1

        for tileEntities in self.TileEntities, self.TileTicks:
            for tileEntity in tileEntities:
                if "y" in tileEntity:
                    tileEntity["y"].value = self.Height - tileEntity["y"].value - 1

    # Width of paintings
    # pcm1k TODO - this can probably go in the version data
    paintingMap = {'Kebab': 1,
                   'Aztec': 1,
                   'Alban': 1,
                   'Aztec2': 1,
                   'Bomb': 1,
                   'Plant': 1,
                   'Wasteland': 1,
                   'Wanderer': 1,
                   'Graham': 1,
                   'Pool': 2,
                   'Courbet': 2,
                   'Sunset': 2,
                   'Sea': 2,
                   'Creebet': 2,
                   'Match': 2,
                   'Stage': 2,
                   'Void': 2,
                   'SkullAndRoses': 2,
                   'Wither': 2,
                   'Fighters': 4,
                   'Skeleton': 4,
                   'DonkeyKong': 4,
                   'Pointer': 4,
                   'Pigscene': 4,
                   'BurningSkull': 4}

    def flipNorthSouthBlocks(self):
        blockrotation.FlipNorthSouth(self.Blocks, self.Data, mats=self.materials)

    def flipNorthSouth(self):
        self._Blocks = self._Blocks[::-1, :, :]  # x=-x
        self._Data = self._Data[::-1, :, :]
        if "Biomes" in self.root_tag:
            self.root_tag["Biomes"].value = self.root_tag["Biomes"].value[:, ::-1]
        self.flipNorthSouthBlocks()
        self._flipNorthSouthEntities()

    def _flipNorthSouthEntities(self):
        self._fakeEntities = None

        paintingFlipX = [0, 3, 2, 1]

        log.info(u"N/S Flip: Relocating entities...")
        for entity in self.Entities:
            entity["Pos"][0].value = self.Width - entity["Pos"][0].value
            if "Motion" in entity:
                entity["Motion"][0].value = -entity["Motion"][0].value

            if "Rotation" in entity:
                entity["Rotation"][0].value = -entity["Rotation"][0].value

            # Special logic for old width painting as TileX/TileZ favours -x/-z

            facing = self._getPaintingFacing(entity)
            if facing is not None and "TileX" in entity and "TileZ" in entity:
                entity["TileX"].value = self.Width - entity["TileX"].value - 1
                if "Motive" in entity and self.paintingMap.get(entity["Motive"].value, 1) % 2 == 0:
                    if facing.value == 0: # south
                        entity["TileX"].value -= 1
                    elif facing.value == 2: # north
                        entity["TileX"].value += 1
                    elif facing.value == 1: # west
                        entity["TileZ"].value += 1
                    elif facing.value == 3: # east
                        entity["TileZ"].value -= 1
                facing.value = paintingFlipX[facing.value]

        for tileEntities in self.TileEntities, self.TileTicks:
            for tileEntity in tileEntities:
                if "x" in tileEntity:
                    tileEntity["x"].value = self.Width - tileEntity["x"].value - 1

    def flipEastWestBlocks(self):
        blockrotation.FlipEastWest(self.Blocks, self.Data, mats=self.materials)

    def flipEastWest(self):
        self._Blocks = self._Blocks[:, ::-1, :]  # z=-z
        self._Data = self._Data[:, ::-1, :]
        if "Biomes" in self.root_tag:
            self.root_tag["Biomes"].value = self.root_tag["Biomes"].value[::-1, :]
        self.flipEastWestBlocks()
        self._flipEastWestEntities()

    def _flipEastWestEntities(self):
        self._fakeEntities = None

        paintingFlipZ = [2, 1, 0, 3]

        log.info(u"E/W Flip: Relocating entities...")
        for entity in self.Entities:
            entity["Pos"][2].value = self.Length - entity["Pos"][2].value
            if "Motion" in entity:
                entity["Motion"][2].value = -entity["Motion"][2].value

            if "Rotation" in entity:
                entity["Rotation"][0].value = 180 - entity["Rotation"][0].value

            # Special logic for old width painting as TileX/TileZ favours -x/-z

            facing = self._getPaintingFacing(entity)
            if facing is not None and "TileX" in entity and "TileZ" in entity:
                entity["TileZ"].value = self.Length - entity["TileZ"].value - 1
                if "Motive" in entity and self.paintingMap.get(entity["Motive"].value, 1) % 2 == 0:
                    if facing.value == 1: # west
                        entity["TileZ"].value -= 1
                    elif facing.value == 3: # east
                        entity["TileZ"].value += 1
                    elif facing.value == 0: # south
                        entity["TileX"].value += 1
                    elif facing.value == 2: # north
                        entity["TileX"].value -= 1
                facing.value = paintingFlipZ[facing.value]

        for tileEntities in self.TileEntities, self.TileTicks:
            for tileEntity in tileEntities:
                if "z" in tileEntity:
                    tileEntity["z"].value = self.Length - tileEntity["z"].value - 1

    def setBlockDataAt(self, x, y, z, newdata):
        if (x, y, z) not in self.bounds:
            return 0
        self.Data[x, z, y] = (newdata & 0xf)

    def blockDataAt(self, x, y, z):
        if (x, y, z) not in self.bounds:
            return 0
        return self.Data[x, z, y]

    def biomeAt(self, x, z, y=0):
        if (x, y, z) not in self.bounds:
            return 0
        return self.Biomes[x, z]

    def setBiomeAt(self, x, z, biomeID, y=0):
        if (x, y, z) not in self.bounds:
            return 0
        self.Biomes[x, z] = biomeID

    @classmethod
    def chestWithItemID(cls, itemID, count=64, damage=0):
        """ Creates a chest with a stack of 'itemID' in each slot.
        Optionally specify the count of items in each stack. Pass a negative
        value for damage to create unnaturally sturdy tools. """
        root_tag = nbt.TAG_Compound()
        invTag = nbt.TAG_List()
        root_tag["Inventory"] = invTag
        for slot in xrange(9, 36):
            itemTag = nbt.TAG_Compound()
            itemTag["Slot"] = nbt.TAG_Byte(slot)
            itemTag["Count"] = nbt.TAG_Byte(count)
            itemTag["id"] = nbt.TAG_Short(itemID)
            itemTag["Damage"] = nbt.TAG_Short(damage)
            invTag.append(itemTag)

        chest = INVEditChest(root_tag, "")

        return chest

    def getChunk(self, cx, cz):
        chunk = super(MCSchematic, self).getChunk(cx, cz)
        if "Biomes" in self.root_tag:
            x = cx << 4
            z = cz << 4
            chunk.Biomes = self.Biomes[x:x + 16, z:z + 16]
        return chunk


class INVEditChest(MCSchematic):
    Width = 1
    Height = 1
    Length = 1
    Blocks = None
    Data = array([[[0]]], dtype="uint8")
    Entities = nbt.TAG_List()
    _materials = alphaMaterials

    @classmethod
    def _isTagLevel(cls, root_tag):
        return "Inventory" in root_tag

    def __init__(self, root_tag, filename):

        self.Blocks = array([[[self.materials.Chest.ID]]], dtype="uint8")

        if filename:
            self.filename = filename
            if None is root_tag:
                try:
                    root_tag = nbt.load(filename)
                except IOError as e:
                    log.info(u"Failed to load file {0}".format(e))
                    raise
        else:
            assert root_tag, "Must have either root_tag or filename"
            self.filename = None

        for item in list(root_tag["Inventory"]):
            slot = item["Slot"].value
            if slot < 9 or slot >= 36:
                root_tag["Inventory"].remove(item)
            else:
                item["Slot"].value -= 9  # adjust for different chest slot indexes

        self.root_tag = root_tag

    @property
    def TileEntities(self):
        chestTag = nbt.TAG_Compound()
        chestTag["id"] = nbt.TAG_String("Chest")
        chestTag["Items"] = nbt.TAG_List(self.root_tag["Inventory"])
        chestTag["x"] = nbt.TAG_Int(0)
        chestTag["y"] = nbt.TAG_Int(0)
        chestTag["z"] = nbt.TAG_Int(0)

        return nbt.TAG_List([chestTag], name="TileEntities")


class ZipSchematic(infiniteworld.MCInfdevOldLevel):
    def __init__(self, filename, create=False):
        self.zipfilename = filename

        tempdir = tempfile.mktemp("schematic")
        if create is False:
            zf = zipfile.ZipFile(filename, allowZip64=True)
            zf.extractall(tempdir)
            zf.close()
            # see commits 698c959cd, fe1324274, 303eb675c for why this is needed
            tempRegionPath = os.path.join(tempdir, "##MCEDIT.TEMP##", "region")
            if os.path.exists(tempRegionPath):
                shutil.move(tempRegionPath, os.path.join(tempdir, "region"))

        super(ZipSchematic, self).__init__(tempdir, create)
        self.minY = 0
        atexit.register(shutil.rmtree, self.worldFolder.filename, True)

        try:
            schematicDat = nbt.load(self.worldFolder.getFilePath("schematic.dat"))

            self.Width = schematicDat['Width'].value
            self.Height = schematicDat['Height'].value
            self.Length = schematicDat['Length'].value

            if "Materials" in schematicDat:
                self.materials = namedMaterials[schematicDat["Materials"].value]

        except Exception as e:
            print "Exception reading schematic.dat, skipping: {0!r}".format(e)
            self.Width = 0
            self.Length = 0

    def __del__(self):
        shutil.rmtree(self.worldFolder.filename, True)

    def saveInPlaceGen(self):
        self.saveToFile(self.zipfilename)
        yield

    def saveToFile(self, filename):
        for _ in super(ZipSchematic, self).saveInPlaceGen():
            pass
        schematicDat = nbt.TAG_Compound()
        schematicDat.name = "Mega Schematic"

        schematicDat["Width"] = nbt.TAG_Int(self.size[0])
        schematicDat["Height"] = nbt.TAG_Int(self.size[1])
        schematicDat["Length"] = nbt.TAG_Int(self.size[2])
        schematicDat["Materials"] = nbt.TAG_String(self.materials.name)

        schematicDat.save(self.worldFolder.getFilePath("schematic.dat"))

        basedir = self.worldFolder.filename
        assert os.path.isdir(basedir)

        with closing(zipfile.ZipFile(filename, "w", zipfile.ZIP_STORED, allowZip64=True)) as z:
            for root, dirs, files in os.walk(basedir):
                # NOTE: ignore empty directories
                for fn in files:
                    absfn = os.path.join(root, fn)
                    zfn = absfn[len(basedir) + len(os.sep):]  # XXX: relative path
                    z.write(absfn, zfn)

    def getWorldBounds(self):
        return BoundingBox((0, self.minY, 0), (self.Width, self.Height, self.Length))

    @classmethod
    def _isLevel(cls, filename):
        return zipfile.is_zipfile(filename)


# pcm1k TODO - maybe have a SchematicBase class instead of using MCSchematic?
class SpongeSchematic(MCSchematic):
    NON_ALPHA_VERSION = 0x7FFFFFFF

    def _load(self, root_tag, mats=None):
        def handleBlockData(dataTag, palette, blocks, data, mats):
            decodeSignedVarInt = self._decodeSignedVarInt
            deStringifyBlockstate = BlockstateAPI.deStringifyBlockstate
            blockstateToID = mats.blockstate_api.blockstateToID

            buf = (byte for byte in dataTag.value)
            stateCache = {}
            cacheGet = stateCache.get
            # we need the iteration order to be (x, z, y), but ndindex() does it in reverse order, so use swapaxes()
            for y, z, x in ndindex(swapaxes(blocks, 0, 2).shape):
                paletteI = decodeSignedVarInt(buf)
                if paletteI is None:
                    return

                block = cacheGet(paletteI)
                if block is None:
                    name, properties = deStringifyBlockstate(palette[paletteI])
                    stateCache[paletteI] = block = blockstateToID(name, properties, create=True)
                blockID, blockData = block
                if blockID == -1 or blockData == -1:
                    continue

                blocks[x, z, y] = blockID
                data[x, z, y] = blockData

        def handleBlocks(blocksTag):
            if blocksTag is None:
                return
            palette = {value.value: key for key, value in blocksTag["Palette"].iteritems()}
            handleBlockData(blocksTag["Data"], palette, self.Blocks, self.Data, self.materials)

            blockEntitiesTag = blocksTag.get("BlockEntities")
            if blockEntitiesTag is None:
                return
            tileEntities = self.TileEntities
            for e in blockEntitiesTag:
                entity = e.get("Data", nbt.TAG_Compound())
                entity["id"] = e["Id"]
                entity["x"], entity["y"], entity["z"] = [nbt.TAG_Int(p) for p in e["Pos"].value]
#                TileEntity.setpos(entity, e["Pos"].value)
                tileEntities.append(entity)

        def handleBiomeData(dataTag, palette, biomes, biomeTypes):
            decodeSignedVarInt = self._decodeSignedVarInt
            biomeWithStringID = biomeTypes.biomeWithStringID

            buf = (byte for byte in dataTag.value)
            stateCache = {}
            cacheGet = stateCache.get
            # we need the iteration order to be (x, z, y), but ndindex() does it in reverse order, so use swapaxes()
            for y, z, x in ndindex(swapaxes(biomes, 0, 2).shape):
                paletteI = decodeSignedVarInt(buf)
                if paletteI is None:
                    return

                biomeID = cacheGet(paletteI)
                if biomeID is None:
                    biome = biomeWithStringID(palette[paletteI], create=True)
                    stateCache[paletteI] = biomeID = biome.ID if biome is not None else -1
                if biomeID == -1:
                    continue

                biomes[x, z, y] = biomeID

        def handleBiomes(biomesTag):
            if biomesTag is None:
                return
            palette = {value.value: key for key, value in biomesTag["Palette"].iteritems()}
            handleBiomeData(biomesTag["Data"], palette, self.Biomes, self.biomeTypes)

        def handleEntities(entitiesTag):
            if entitiesTag is None:
                return
            entities = self.Entities
            for e in entitiesTag:
                entity = e.get("Data", nbt.TAG_Compound())
                entity["id"] = e["Id"]
                entity["Pos"] = e["Pos"]
                entities.append(entity)

        def getPlatVer(dataVersion):
            if dataVersion != self.NON_ALPHA_VERSION:
                mceditTag = self.Metadata.get("MCEdit")
                if mceditTag is not None:
                    # these extra tags are not necessary, so remove them
                    mceditTag.pop("DefsPlatform", None)
                    mceditTag.pop("DefsVersion", None)
                return PLATFORM_ALPHA, str(dataVersion)

            mceditTag = self.Metadata["MCEdit"]
            defsPlatform = mceditTag["DefsPlatform"].value
            defsVersion = mceditTag["DefsVersion"].value
            return defsPlatform, defsVersion

        self.root_tag = root_tag
        schemTag = root_tag["Schematic"]

        if schemTag["Version"].value != 3:
            raise IOError("Only SpongeSchematic version 3 is currently supported")

        # pcm1k TODO - defsPlatform and defsVersion are defined, so is this kinda redundant?
        dataVersion = schemTag["DataVersion"].value
        defsPlatform, defsVersion = getPlatVer(dataVersion)
        self.defsIds = defsIds = get_defs_ids(defsPlatform, defsVersion)
        self.materials = getMaterials(defsIds, forceNew=True)

        if DEBUG: log.debug(u"Processing size.")
        w = schemTag["Width"].value
        l = schemTag["Length"].value
        h = schemTag["Height"].value

        self._Blocks = zeros((w, l, h), dtype="uint16")
        self._Data = zeros((w, l, h), dtype="uint16")
        self._Biomes = zeros((w, l, h), dtype="uint16")

        self._Entities = nbt.TAG_List()
        self._TileEntities = nbt.TAG_List()

        handleBlocks(schemTag.pop("Blocks", None))
        handleBiomes(schemTag.pop("Biomes", None))
        handleEntities(schemTag.pop("Entities", None))

    def _create(self, shape, mats=None):
        if DEBUG: log.debug(u"No root tag found, creating a blank schematic.")
        assert shape is not None
        self.root_tag = root_tag = nbt.TAG_Compound()
        root_tag["Schematic"] = schemTag = nbt.TAG_Compound()

        schemTag["Height"] = nbt.TAG_Short(shape[1])
        schemTag["Length"] = nbt.TAG_Short(shape[2])
        schemTag["Width"] = nbt.TAG_Short(shape[0])

        self._Blocks = zeros((shape[0], shape[2], shape[1]), dtype="uint16")
        self._Data = zeros((shape[0], shape[2], shape[1]), dtype="uint16")
        self._Biomes = zeros((shape[0], shape[2], shape[1]), dtype="uint16")

        self._Entities = nbt.TAG_List()
        self._TileEntities = nbt.TAG_List()

        schemTag["Version"] = nbt.TAG_Int(3)

        if mats is None:
            defsIds = get_defs_ids(PLATFORM_ALPHA, VERSION_LATEST)
            self.materials = mats = getMaterials(defsIds, forceNew=True)
        elif mats in namedMaterials:
            if DEBUG: log.debug(u"Using named materials.")
            self.materials = mats = namedMaterials[mats]
        else:
            assert (isinstance(mats, MCMaterials))
            self.materials = mats

        def getDataVersion(defsIds):
            if defsIds.platform != PLATFORM_ALPHA:
                return self.NON_ALPHA_VERSION
            try:
                return int(defsIds.version)
            except ValueError:
                return self.NON_ALPHA_VERSION

        self.defsIds = defsIds = mats.defsIds
        # pcm1k TODO - The dataVersion can be "wrong" if we are exporting from a world and don't have version definitions close to that version. Of course, this does not matter much if we actually have version definitions for that version
        dataVersion = getDataVersion(defsIds)
        schemTag["DataVersion"] = nbt.TAG_Int(dataVersion)
        if dataVersion == self.NON_ALPHA_VERSION:
            metaTag = self.Metadata
            metaTag["MCEdit"] = mceditTag = nbt.TAG_Compound()
            mceditTag["DefsPlatform"] = nbt.TAG_String(defsIds.platform)
            mceditTag["DefsVersion"] = nbt.TAG_String(defsIds.version)

    @staticmethod
    def _encodeSignedVarInt(value):
        value &= 0xFFFFFFFF
        result = []
        while True:
            byte = value & 0x7F
            value >>= 7
            if value == 0:
                result.append(byte)
                break
            result.append(byte | 0x80)
        return result

    @staticmethod
    def _decodeSignedVarInt(input_):
        result = 0
        shift = 0
        for byte in input_:
            if shift >= 32:
                raise IOError("VarInt too big")
            result |= (byte & 0x7F) << shift
            shift += 7
            if (byte & 0x80) == 0:
                if (result & 0x80000000) != 0:
                    return result | -0x100000000
                return result
        return result if shift > 0 else None

    def saveToFile(self, filename=None):
        """ save to file named filename, or use self.filename.  XXX NOT THREAD SAFE AT ALL. """
        if filename is None:
            filename = self.filename
        if filename is None:
            raise IOError, u"Attempted to save an unnamed schematic in place"

        # pcm1k TODO - maybe un-nest this stuff
        def createPalette(usedBlocks):
            usedBlocks = usedBlocks.items()
            # only matters if more than 127 blocks, as everything will fit into 1 byte otherwise
            if len(usedBlocks) > 127:
                # sort to allow more frequent blocks to have a smaller index
                usedBlocks.sort(key=lambda item: item[1], reverse=True)

            paletteTag = nbt.TAG_Compound()
            # apparently TAG_Compound uses a list internally and I want to be reasonably fast
            paletteDict = {}
            for paletteI, entry in enumerate(usedBlocks):
                name = entry[0]
                paletteTag[name] = nbt.TAG_Int(paletteI)
                paletteDict[name] = paletteI
            return paletteTag, paletteDict

        def countBlocks(blocks, data, mats):
            idToBlockstate = mats.blockstate_api.idToBlockstate
            stringifyBlockstate = BlockstateAPI.stringifyBlockstate

            usedBlocks = defaultdict(lambda: 0)
            stateCache = {}
            cacheGet = stateCache.get
            for pos, blockID in ndenumerate(blocks):
                blockData = data[pos]
                state = cacheGet((blockID, blockData))
                if state is None:
                    name, properties = idToBlockstate(blockID, blockData)
                    stateCache[blockID, blockData] = state = stringifyBlockstate(name, properties)

                usedBlocks[state] += 1
            return usedBlocks, stateCache

        def createBlockPalette(blocks, data, mats):
            # "blockToIndex" should really be "blockToState" at this point, it will be converted later
            usedBlocks, blockToIndex = countBlocks(blocks, data, mats)
            paletteTag, paletteDict = createPalette(usedBlocks)
            for block, name in blockToIndex.iteritems():
                blockToIndex[block] = paletteDict[name]
            return paletteTag, blockToIndex

        def createBlockData(blocks, data, blockToIndex):
            encodeSignedVarInt = self._encodeSignedVarInt

            result = []
            # we need the iteration order to be (x, z, y), but ndenumerate() does it in reverse order, so use swapaxes()
            for (y, z, x), blockID in ndenumerate(swapaxes(blocks, 0, 2)):
                blockData = data[x, z, y]
                paletteIndex = blockToIndex[blockID, blockData]
                result.extend(encodeSignedVarInt(paletteIndex))
            resultTag = nbt.TAG_Byte_Array(array(result, dtype="uint8"))
            return resultTag

        def countBiomes(biomes, biomeTypes):
            biomeWithID = biomeTypes.biomeWithID

            usedBiomes = defaultdict(lambda: 0)
            stateCache = {}
            cacheGet = stateCache.get
            # pcm1k TODO - Use nditer()? But then apparently each entry returns a numpy.ndarray?
            for pos, biomeID in ndenumerate(biomes):
                state = cacheGet(biomeID)
                if state is None:
                    biome = biomeWithID(biomeID)
                    stateCache[biomeID] = state = biome.stringID

                usedBiomes[state] += 1
            return usedBiomes, stateCache

        def createBiomePalette(biomes, biomeTypes):
            # "biomeToIndex" should really be "biomeToState" at this point, it will be converted later
            usedBiomes, biomeToIndex = countBiomes(biomes, biomeTypes)
            paletteTag, paletteDict = createPalette(usedBiomes)
            for biome, name in biomeToIndex.iteritems():
                biomeToIndex[biome] = paletteDict[name]
            return paletteTag, biomeToIndex

        def createBiomeData(biomes, biomeToIndex):
            encodeSignedVarInt = self._encodeSignedVarInt

            result = []
            # we need the iteration order to be (x, z, y), but ndenumerate() does it in reverse order, so use swapaxes()
            # pcm1k TODO - Use nditer()? But then apparently each entry returns a numpy.ndarray?
            for (y, z, x), biomeID in ndenumerate(swapaxes(biomes, 0, 2)):
                paletteIndex = biomeToIndex[biomeID]
                result.extend(encodeSignedVarInt(paletteIndex))
            resultTag = nbt.TAG_Byte_Array(array(result, dtype="uint8"))
            return resultTag

        def createBlockEntities(tileEntities):
            result = nbt.TAG_List()
            for e in tileEntities:
                entity = nbt.TAG_Compound()
                entity["Data"] = entityData = copy.deepcopy(e)
                entity["Id"] = entityData.pop("id")
                entity["Pos"] = nbt.TAG_Int_Array((entityData.pop("x").value, entityData.pop("y").value, entityData.pop("z").value))
#                entity["Pos"] = nbt.TAG_Int_Array(TileEntity.pos(entityData))
                result.append(entity)
            return result

        def createEntities(entities):
            result = nbt.TAG_List()
            for e in entities:
                entity = nbt.TAG_Compound()
                entity["Data"] = entityData = copy.deepcopy(e)
                entity["Id"] = entityData.pop("id")
                entity["Pos"] = entityData.pop("Pos")
                result.append(entity)
            return result

        schemTag = self.root_tag["Schematic"]

        schemTag["Blocks"] = blocksTag = nbt.TAG_Compound()
        blocksTag["Palette"], blockToIndex = createBlockPalette(self.Blocks, self.Data, self.materials)
        blocksTag["Data"] = createBlockData(self.Blocks, self.Data, blockToIndex)
        if bool(self.TileEntities):
            blocksTag["BlockEntities"] = createBlockEntities(self.TileEntities)

        schemTag["Biomes"] = biomesTag = nbt.TAG_Compound()
        biomesTag["Palette"], biomeToIndex = createBiomePalette(self.Biomes, self.biomeTypes)
        biomesTag["Data"] = createBiomeData(self.Biomes, biomeToIndex)

        if bool(self.Entities):
            schemTag["Entities"] = createEntities(self.Entities)

        with open(filename, 'wb') as chunkfh:
            self.root_tag.save(chunkfh)

        del schemTag["Blocks"]
        del schemTag["Biomes"]
        schemTag.pop("Entities", None)

    def __str__(self):
        return u"SpongeSchematic(shape={0}, materials={2}, filename=\"{1}\")".format(self.size, self.filename or u"",
                                                                                     self.Materials)

    @property
    def Blocks(self):
        return self._Blocks

    @property
    def Data(self):
        return self._Data

    @property
    def Entities(self):
        return self._Entities

    @property
    def TileEntities(self):
        return self._TileEntities

    @property
    def TileTicks(self):
        metaTag = self.Metadata
        mceditTag = metaTag.get("MCEdit")
        if mceditTag is None:
            metaTag["MCEdit"] = mceditTag = nbt.TAG_Compound()
        tileTicks = mceditTag.get("TileTicks")
        if tileTicks is None:
            mceditTag["TileTicks"] = tileTicks = nbt.TAG_List()
        return tileTicks

    @property
    def Materials(self):
        return self.materials.name

    @property
    def Biomes(self):
        return self._Biomes

    @property
    def Metadata(self):
        schemTag = self.root_tag["Schematic"]
        metaTag = schemTag.get("Metadata")
        if metaTag is None:
            schemTag["Metadata"] = metaTag = nbt.TAG_Compound()
        return metaTag

    @property
    def defsPlatform(self):
        schemTag = self.root_tag["Schematic"]

        dataVersion = schemTag["DataVersion"].value
        if dataVersion != self.NON_ALPHA_VERSION:
            return PLATFORM_ALPHA

        mceditTag = self.Metadata["MCEdit"]
        defsPlatform = mceditTag["DefsPlatform"].value
        return defsPlatform

    @property
    def gameVersionId(self):
        schemTag = self.root_tag["Schematic"]

        dataVersion = schemTag["DataVersion"].value
        if dataVersion != self.NON_ALPHA_VERSION:
            return dataVersion

        return None

    @property
    def defsVersion(self):
        schemTag = self.root_tag["Schematic"]

        dataVersion = schemTag["DataVersion"].value
        if dataVersion != self.NON_ALPHA_VERSION:
            return str(dataVersion)

        mceditTag = self.Metadata["MCEdit"]
        defsVersion = mceditTag["DefsVersion"].value
        return defsVersion

    @classmethod
    def _isTagLevel(cls, root_tag):
        return "Schematic" in root_tag

    def rotateLeft(self):
        self._Blocks = swapaxes(self._Blocks, 0, 1)[:, ::-1, :]  # x=z; z=-x
        self._Data = swapaxes(self._Data, 0, 1)[:, ::-1, :]
        self._Biomes = swapaxes(self._Biomes, 0, 1)[:, ::-1, :]
        self._update_shape()
        self.rotateLeftBlocks()
        self._rotateLeftEntities()

    def roll(self):
        self._Blocks = swapaxes(self._Blocks, 0, 2)[::-1, :, :]  # x=-y; y=x
        self._Data = swapaxes(self._Data, 0, 2)[::-1, :, :]
        self._Biomes = swapaxes(self._Biomes, 0, 2)[::-1, :, :]
        self._update_shape()
        self.rollBlocks()
        self._rollEntities()

    def flipVertical(self):
        self._Blocks = self._Blocks[:, :, ::-1]  # y=-y
        self._Data = self._Data[:, :, ::-1]
        self._Biomes = self._Biomes[:, :, ::-1]
        self.flipVerticalBlocks()
        self._flipVerticalEntities()

    def flipNorthSouth(self):
        self._Blocks = self._Blocks[::-1, :, :]  # x=-x
        self._Data = self._Data[::-1, :, :]
        self._Biomes = self._Biomes[::-1, :, :]
        self.flipNorthSouthBlocks()
        self._flipNorthSouthEntities()

    def flipEastWest(self):
        self._Blocks = self._Blocks[:, ::-1, :]  # z=-z
        self._Data = self._Data[:, ::-1, :]
        self._Biomes = self._Biomes[:, ::-1, :]
        self.flipEastWestBlocks()
        self._flipEastWestEntities()

    def biomeAt(self, x, z, y=0):
        if (x, y, z) not in self.bounds:
            return 0
        return self.Biomes[x, z, y]

    def setBiomeAt(self, x, z, biomeID, y=0):
        if (x, y, z) not in self.bounds:
            return 0
        self.Biomes[x, z, y] = biomeID

    def getChunk(self, cx, cz):
#        chunk = super(MCSchematic, self).getChunk(cx, cz)
        chunk = EntityLevel.getChunk(self, cx, cz)
        x = cx << 4
        z = cz << 4
        chunk.Biomes = self.Biomes[x:x + 16, z:z + 16]
        return chunk


# pcm1k TODO - a bunch of this can probably be rewritten
class StructureNBT(object):
    SUPPORTED_VERSIONS = [1, ]

    def __init__(self, filename=None, root_tag=None, size=None, mats=alphaMaterials, version=None, author=None):
        self._author = author
        self._blocks = None
        self._palette = None
        self._entities = []
        self._tile_entities = None
        self._size = None
        self._version = version
        self._mat = mats
        self.blockstate = mats.blockstate_api

        if filename:
            root_tag = nbt.load(filename)

        def loadPalette(paletteTag):
            result = []
            for state in paletteTag:
                if "Properties" in state:
                    properties = {key: value.value for key, value in state["Properties"].iteritems()}
                else:
                    properties = {}
                result.append((state["Name"].value, properties))
            return result

        if root_tag:
            self._root_tag = root_tag
            self._size = (self._root_tag["size"][0].value, self._root_tag["size"][1].value, self._root_tag["size"][2].value)

            self._author = self._root_tag.get("author", nbt.TAG_String()).value
            self._version = self._root_tag.get("DataVersion", nbt.TAG_Int(1)).value

            self._palette = loadPalette(self._root_tag["palette"])

            self._blocks = zeros(self.Size, dtype=tuple)
            self._blocks.fill((0, 0))
            self._entities = []
            self._tile_entities = zeros(self.Size, dtype=nbt.TAG_Compound)
            self._tile_entities.fill({})

            for block in self._root_tag["blocks"]:
                x, y, z = [p.value for p in block["pos"].value]
                blockID, blockData = self.blockstate.blockstateToID(*self.get_state(block["state"].value))
                if blockID == -1 or blockData == -1:
                    continue
                self._blocks[x, y, z] = blockID, blockData
                if "nbt" in block:
                    compound = nbt.TAG_Compound()
                    compound.update(block["nbt"])
                    self._tile_entities[x, y, z] = compound

            for e in self._root_tag["entities"]:
                entity = e["nbt"]
                entity["Pos"] = e["pos"]
                self._entities.append(entity)
        elif size:
            self._root_tag = nbt.TAG_Compound()
            self._size = size

            self._blocks = zeros(self.Size, dtype=tuple)
            self._blocks.fill((0, 0))
            self._entities = []
            self._tile_entities = zeros(self.Size, dtype=nbt.TAG_Compound)
            self._tile_entities.fill({})

    def toSchematic(self):
        schem = MCSchematic(shape=self.Size, mats=self._mat)
        for (x, y, z), value in ndenumerate(self._blocks):
            b_id, b_data = value
            schem.Blocks[x, z, y] = b_id
            schem.Data[x, z, y] = b_data

        for (x, y, z), value in ndenumerate(self._tile_entities):
            if not value:
                continue
            tag = value
            tag["x"] = nbt.TAG_Int(x)
            tag["y"] = nbt.TAG_Int(y)
            tag["z"] = nbt.TAG_Int(z)
            schem.addTileEntity(tag)

        entity_list = nbt.TAG_List()
        for e in self._entities:
            entity_list.append(e)
        schem.root_tag["Entities"] = entity_list

        return schem

    @classmethod
    def fromSchematic(cls, schematic, **kwargs):
        structure = cls(size=(schematic.Width, schematic.Height, schematic.Length), mats=schematic.materials, **kwargs)
        schematic = copy.copy(schematic)

        for (x, z, y), b_id in ndenumerate(schematic.Blocks):
            data = schematic.Data[x, z, y]
            structure._blocks[x, y, z] = (b_id, data)

        for te in schematic.TileEntities:
            x, y, z = te["x"].value, te["y"].value, te["z"].value
            del te["x"]
            del te["y"]
            del te["z"]
            structure._tile_entities[x, y, z] = te

        for e in schematic.Entities:
            structure._entities.append(e)
        return structure

    # pcm1k TODO - might put this in nbt.py or something
    def __nbtToDict(self, _nbt):
        if isinstance(_nbt, nbt.TAG_Compound):
            d = {}
            for key in _nbt.iterkeys():
                if isinstance(_nbt[key], nbt.TAG_Compound):
                    d[key] = self.__nbtToDict(_nbt[key])
                elif isinstance(_nbt[key], nbt.TAG_List):
                    l = []
                    for value in _nbt[key]:
                        if isinstance(value, nbt.TAG_Compound):
                            l.append(self.__nbtToDict(value))
                        else:
                            l.append(value.value)
                    d[key] = l
                else:
                    d[key] = _nbt[key].value
            return d
        elif isinstance(_nbt, nbt.TAG_List):
            l = []
            for tag in _nbt:
                if isinstance(tag, nbt.TAG_Compound):
                    l.append(self.__nbtToDict(tag))
                elif isinstance(tag, nbt.TAG_List):
                    l.append(self.__nbtToDict(tag))
                else:
                    l.append(tag.value)
            return l
        return _nbt

    def get_state(self, index):
        return self._palette[index]

    # pcm1k TODO - this is unused
    def get_palette_index(self, name, properties=None):  # TODO: Switch to string comparison of properties, instead of dict comparison
        for i in xrange(len(self._palette)):
            if self._palette[i][0] == name:
                if properties is not None:
                    for key, value in properties.iteritems():
                        if self._palette[i][1].get(key, None) != value:
                            continue
                return i
        return -1

    def save(self, filename=""):
        if not self._author:
            self._author = "MCEdit-Unified"

        structure_tag = nbt.TAG_Compound()
        structure_tag["author"] = nbt.TAG_String(self._author)
        if self._version:
            structure_tag["DataVersion"] = nbt.TAG_Int(self.DataVersion)
        else:
            structure_tag["DataVersion"] = nbt.TAG_Int(self.SUPPORTED_VERSIONS[-1])

        structure_tag["size"] = nbt.TAG_List(
                                             [
                                              nbt.TAG_Int(self.Size[0]),
                                              nbt.TAG_Int(self.Size[1]),
                                              nbt.TAG_Int(self.Size[2])
                                              ]
                                             )

        def addToPalette(palette_tag, name, properties):
            state = nbt.TAG_Compound()
            state["Name"] = nbt.TAG_String(name)

            if properties:
                props = nbt.TAG_Compound()
                for key, value in properties.iteritems():
                    props[key] = nbt.TAG_String(value)
                state["Properties"] = props

            palette_tag.append(state)

        blockstate_api = self.blockstate
        index_table = {}

        blocks_tag = nbt.TAG_List()
        palette_tag = nbt.TAG_List()
        for z in xrange(self._blocks.shape[2]):  # For some reason, ndenumerate() didn't work, but this does
            for x in xrange(self._blocks.shape[0]):
                for y in xrange(self._blocks.shape[1]):

                    value = self._blocks[x, y, z]
                    name, properties = blockstate_api.idToBlockstate(*value)
                    blockstate = BlockstateAPI.stringifyBlockstate(name, properties)

                    index = index_table.get(blockstate)
                    if index is None:
                        index_table[blockstate] = index = len(index_table)
                        addToPalette(palette_tag, name, properties)

                    block = nbt.TAG_Compound()
                    block["state"] = nbt.TAG_Int(index)
                    block["pos"] = nbt.TAG_List(
                                        [
                                         nbt.TAG_Int(x),
                                         nbt.TAG_Int(y),
                                         nbt.TAG_Int(z)
                                         ]
                                        )

                    if self._tile_entities[x, y, z]:
                        block["nbt"] = self._tile_entities[x, y, z]

                    blocks_tag.append(block)
        structure_tag["blocks"] = blocks_tag
        structure_tag["palette"] = palette_tag

        entities_tag = nbt.TAG_List()
        for e in self._entities:
            entity = nbt.TAG_Compound()
            pos = e["Pos"]
            entity["pos"] = pos
            entity["nbt"] = e
            blockPos = nbt.TAG_List()
            for coord in pos:
                blockPos.append(nbt.TAG_Int(math.floor(coord.value)))
            entity["blockPos"] = blockPos

            entities_tag.append(entity)

        structure_tag["entities"] = entities_tag
        structure_tag.save(filename)

    @property
    def Author(self):
        return self._author

    @property
    def Size(self):
        return self._size

    @property
    def Blocks(self):
        return self._blocks

    @property
    def Entities(self):
        return self._entities

    @property
    def Palette(self):
        return self._palette

    @property
    def DataVersion(self):
        return self._version


def adjustExtractionParameters(self, box):
    x, y, z = box.origin
    w, h, l = box.size
    destX = destY = destZ = 0

    if y < self.minY:
        destY += self.minY - y
        h -= self.minY - y
        y = self.minY

    if y >= self.maxY:
        return

    if y + h >= self.maxY:
        h = self.maxY - y

    if h <= 0:
        return

    if self.Width:
        if x < 0:
            w += x
            destX -= x
            x = 0
        if x >= self.Width:
            return

        if x + w >= self.Width:
            w = self.Width - x

        if w <= 0:
            return

        if z < 0:
            l += z
            destZ -= z
            z = 0

        if z >= self.Length:
            return

        if z + l >= self.Length:
            l = self.Length - z

        if l <= 0:
            return

    box = BoundingBox((x, y, z), (w, h, l))

    return box, (destX, destY, destZ)


# pcm1k TODO - Make this return a SpongeSchematic? And instead have an extractOldSchematicFrom?
def extractSchematicFrom(sourceLevel, box, entities=True, cancelCommandBlockOffset=False):
    return exhaust(extractSchematicFromIter(sourceLevel, box, entities, cancelCommandBlockOffset))


def extractSchematicFromIter(sourceLevel, box, entities=True, cancelCommandBlockOffset=False):
    p = sourceLevel.adjustExtractionParameters(box)
    if p is None:
        yield None
        return
    newbox, destPoint = p

    tempSchematic = MCSchematic(shape=box.size, mats=sourceLevel.materials)
    for i in tempSchematic.copyBlocksFromIter(sourceLevel, newbox, destPoint, entities=entities, biomes=True, first=True, cancelCommandBlockOffset=cancelCommandBlockOffset):
        yield i

    yield tempSchematic


def extractSpongeSchematicFrom(sourceLevel, box, entities=True):
    return exhaust(extractSpongeSchematicFromIter(sourceLevel, box, entities))


def extractSpongeSchematicFromIter(sourceLevel, box, entities=True):
    p = sourceLevel.adjustExtractionParameters(box)
    if p is None:
        yield None
        return
    newbox, destPoint = p

    tempSchematic = SpongeSchematic(shape=box.size, mats=sourceLevel.materials)
    for i in tempSchematic.copyBlocksFromIter(sourceLevel, newbox, destPoint, entities=entities, biomes=True, first=True):
        yield i

    yield tempSchematic


MCLevel.extractSchematic = extractSchematicFrom
MCLevel.extractSchematicIter = extractSchematicFromIter
MCLevel.extractSpongeSchematic = extractSpongeSchematicFrom
MCLevel.extractSpongeSchematicIter = extractSpongeSchematicFromIter
MCLevel.adjustExtractionParameters = adjustExtractionParameters

import tempfile


def extractZipSchematicFrom(sourceLevel, box, zipfilename=None, entities=True):
    return exhaust(extractZipSchematicFromIter(sourceLevel, box, zipfilename, entities))


def extractZipSchematicFromIter(sourceLevel, box, zipfilename=None, entities=True, cancelCommandBlockOffset=False):
    # converts classic blocks to alpha
    # probably should only apply to alpha levels

    if zipfilename is None:
        zipfilename = tempfile.mktemp("zipschematic.zip")
    atexit.register(shutil.rmtree, zipfilename, True)

    p = sourceLevel.adjustExtractionParameters(box)
    if p is None:
        return
    sourceBox, destPoint = p

    destPoint = (0, 0, 0)

    tempSchematic = ZipSchematic(zipfilename, create=True)
    tempSchematic.materials = sourceLevel.materials
    tempSchematic.Width, tempSchematic.Height, tempSchematic.Length = sourceBox.size

    for i in tempSchematic.copyBlocksFromIter(sourceLevel, sourceBox, destPoint, entities=entities, create=True,
                                              biomes=True, first=True, cancelCommandBlockOffset=cancelCommandBlockOffset):
        yield i

    tempSchematic.saveInPlace()  # lights not needed for this format - crashes minecraft though
    yield tempSchematic


MCLevel.extractZipSchematic = extractZipSchematicFrom
MCLevel.extractZipSchematicIter = extractZipSchematicFromIter


def extractAnySchematic(level, box):
    return exhaust(level.extractAnySchematicIter(box))


def extractAnySchematicIter(level, box):
    if box.chunkCount < infiniteworld.MCInfdevOldLevel.loadedChunkLimit:
        for i in level.extractSchematicIter(box):
            yield i
    else:
        for i in level.extractZipSchematicIter(box):
            yield i


MCLevel.extractAnySchematic = extractAnySchematic
MCLevel.extractAnySchematicIter = extractAnySchematicIter
