from logging import getLogger
from numpy import zeros, rollaxis, indices
import traceback
from os.path import join
from collections import defaultdict
from pprint import pformat
import mclangres
import json
import os
import pkg_resources
from id_definitions import get_defs_ids, PLATFORM_ALPHA, PLATFORM_CLASSIC, PLATFORM_INDEV, PLATFORM_POCKET, VERSION_LATEST

NOTEX = (496, 496)

log = getLogger(__name__)

try:
    pkg_resources.resource_exists(__name__, "mcver")
except:
    import sys
    if getattr(sys, '_MEIPASS', None):
        base = getattr(sys, '_MEIPASS')
        pkg_resources.resource_exists = lambda n,f: os.path.join(base, 'pymclevel', f)

class Block(object):
    """
    Value object representing an (id, data) pair.
    Provides elements of its parent material's block arrays.
    Blocks will have (name, ID, blockData, aka, color, brightness, opacity, blockTextures)
    """

    def __str__(self):
        return "<Block {name} ({id}:{data})>".format(
            name=self.name, id=self.ID, data=self.blockData)

    def __repr__(self):
        return str(self)

    def __cmp__(self, other):
        if not isinstance(other, Block):
            return -1
        key = lambda a: a and (a.ID, a.blockData)
        return cmp(key(self), key(other))

    def __hash__(self):
        return hash((self.ID, self.blockData))

    def __init__(self, materials, blockID, blockData=0):
        self.materials = materials
        self.ID = blockID
        self.blockData = blockData

    @property
    def name(self):
        return self.materials.names[self.ID][self.blockData]

    @property
    def aka(self):
        return self.materials.aka[self.ID][self.blockData]

    @property
    def color(self):
        return self.materials.color[self.ID][self.blockData]

    @property
    def brightness(self):
        return self.materials.brightness[self.ID]

    @property
    def opacity(self):
        return self.materials.opacity[self.ID]

    @property
    def type(self):
        return self.materials.type[self.ID][self.blockData]

    @property
    def search(self):
        return self.materials.search[self.ID][self.blockData]

    @property
    def blockTextures(self):
        return self.materials.blockTextures[self.ID]

    @property
    def namespace(self):
        return self.materials.namespace[self.ID]

    @property
    def idStr(self):
        return self.materials.idStr[self.ID]

    @property
    def stringID(self):
        """Like idStr, but also includes the namespace"""
        return "%s:%s" % (self.namespace, self.idStr)

    @property
    def properties(self):
        return self.materials.properties[self.ID][self.blockData]

    @property
    def Blockstate(self):
        return self.stringID, self.properties


id_limit = 4096
data_limit = 16


class BlockstateAPI(object):
    """
    An easy API to convert from numerical ID's to Blockstates and vice-versa. Each
    material has its own instance of this class. You can access it in a variety of ways::

        from pymclevel.materials import BlockstateAPI, alphaMaterials, pocketMaterials

        api = BlockStateAPI.material_map[alphaMaterials]

        api = alphaMaterials.blockstate_api
    """
    material_map = {}
    # unused
    blockstates = {}

    def __init__(self, mats):
        self._mats = mats
        self.block_map = {}

        self._initBlockMap()

        # pcm1k - why is this even needed?
        self.material_map[self._mats] = self

    def _initBlockMap(self):
        self.block_map.clear()
        for b in self._mats:
            self.block_map[b.ID] = b.stringID

    def idToBlockstate(self, bid, data):
        """
        Converts from a numerical ID to a BlockState string

        :param bid: The ID of the block
        :type bid: int
        :param data: The data value of the block
        :type data: int
        :return: A tuple of BlockState name and it's properties
        :rtype: tuple
        """
        if bid not in self.block_map:
            return "mcedit:unknown_%s" % bid, {"data": data}

        name = self.block_map[bid]
        block = self._mats[bid, data]

        if block.properties is None:
            return "mcedit:unknown_%s" % bid, {"data": data}
        return name, block.properties

    def blockstateToID(self, name, properties):
        """
        Converts from a BlockState to a numerical ID/Data pair

        :param name: The BlockState name
        :type name: str
        :param properties: A list of Property/Value pairs in dict form
        :type properties: list
        :return: A tuple containing the numerical ID/Data pair (<id>, <data>)
        :rtype: tuple
        """
        if name.startswith("mcedit:unknown_"):
            bid = int(name[15:])
            data = int(properties["data"])
            return bid, data

        try:
            block = self._mats[name]
        except KeyError:
            return -1, -1

        def compareDicts(dict1, dict2):
            if dict1 is None or dict2 is None:
                return False
            for key, value in dict2.iteritems():
                if key in dict1 and dict1[key] != value:
                    return False
            return True

        bid = block.ID
        for propI in xrange(len(self._mats.properties[bid])):
            if compareDicts(self._mats.properties[bid][propI], properties):
                return bid, propI
        return bid, block.blockData

    @staticmethod
    def stringifyBlockstate(name, properties):
        """
        Turns a Blockstate into a single string

        :param name: The Block's base name. IE: grass, command_block, etc.
        :type name: str
        :param properties: A list of Property/Value pairs in dict form
        :type properties: list
        :return: A complete Blockstate in string form
        :rtype: str
        """
        if ":" not in name:
            name = "minecraft:%s" % name
        if not properties:
            return name
        result = name + "["
        for (key, value) in properties.iteritems():
            result += "{}={},".format(key, value)
        return result[:-1] + "]"

    @staticmethod
    def deStringifyBlockstate(blockstate):
        """
        Turns a single Blockstate string into a base name, properties tuple

        :param blockstate: The Blockstate string
        :type blockstate: str
        :return: A tuple containing the base name and the properties for the Blockstate
        :rtype: tuple
        """
        seperated = blockstate.split("[")

        if len(seperated) == 1:
            if ":" not in seperated[0]:
                seperated[0] = "minecraft:%s" % seperated[0]
            return seperated[0], {}

        name, props = seperated

        if ":" not in name:
            name = "minecraft:%s" % name

        properties = {}

        props = props[:-1]
        props = props.split(",")
        for prop in props:
            prop = prop.split("=")
            properties[prop[0]] = prop[1]
        return name, properties


class MCMaterials(object):
    defaultColor = (201, 119, 240, 255)
    defaultBrightness = 0
    defaultOpacity = 15
    defaultTexture = NOTEX
    defaultTex = [t // 16 for t in defaultTexture]

    def __init__(self, name, defaultName="Unused Block"):
        object.__init__(self)
        self.yamlDatas = []
        self.defsIds = None

        self.name = name
        self.defaultName = defaultName

        self.blockTextures = zeros((id_limit, data_limit, 6, 2), dtype='uint16')
        # Sets the array size for terrain.png
        self.blockTextures[:] = self.defaultTexture
        self.names = [[defaultName] * data_limit for _ in xrange(id_limit)]
        self.aka = [[""] * data_limit for _ in xrange(id_limit)]
        self.search = [[""] * data_limit for _ in xrange(id_limit)]
        self.properties = [[None] * data_limit for _ in xrange(id_limit)]

        self.type = [["NORMAL"] * data_limit] * id_limit
        self.blocksByType = defaultdict(list)
        self.allBlocks = []
        self.blocksByID = {}

        self.lightEmission = zeros(id_limit, dtype='uint8')
        self.lightEmission[:] = self.defaultBrightness
        self.lightAbsorption = zeros(id_limit, dtype='uint8')
        self.lightAbsorption[:] = self.defaultOpacity
        self.flatColors = zeros((id_limit, data_limit, 4), dtype='uint8')
        self.flatColors[:] = self.defaultColor

        self.idStr = [""] * id_limit
        self.namespace = [""] * id_limit

        self.id_limit = id_limit
        self.data_limit = data_limit

        self.color = self.flatColors
        self.brightness = self.lightEmission
        self.opacity = self.lightAbsorption
        self.types = {}

        self.blockstate_api = BlockstateAPI(self)

        self.Air = self.addBlock(0,
                                 name="Air",
                                 texture=(0, 336),
                                 opacity=0,
                                 idStr="air",
        )

    def __repr__(self):
        return "<MCMaterials ({0})>".format(self.name)

    @property
    def AllStairs(self):
        return [b for b in self.allBlocks if "Stairs" in b.name]

    @property
    def AllSlabs(self):
        return [b for b in self.allBlocks if "Slab" in b.name]

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __len__(self):
        return len(self.allBlocks)

    def __iter__(self):
        return iter(self.allBlocks)

    def _findBlock(self, key):
        lowest_block = None
        for b in self.allBlocks:
            if b.name.lower() == key:
                return b
            if b.stringID.lower() == key:
                if b.blockData == 0:
                    return b
                elif lowest_block is None:
                    lowest_block = b
                elif b.blockData < lowest_block.blockData:
                    lowest_block = b
        return lowest_block

    def __getitem__(self, key):
        """ Let's be magic. If we get a string, return the first block whose
            name matches exactly. If we get a (id, data) pair or an id, return
            that block. for example:

                level.materials[0]  # returns Air
                level.materials["Air"]  # also returns Air
                level.materials["Powered Rail"]  # returns Powered Rail
                level.materials["Lapis Lazuli Block"]  # in Classic

           """
        if isinstance(key, basestring):
            key = key.lower()
            if ":" not in key:
                key = "minecraft:%s" % key
            block = self._findBlock(key)
            if block is not None:
                return block
            # pcm1k - this can probably be improved
            if "[" in key:
                name, properties = self.blockstate_api.deStringifyBlockstate(key)
                block = self._findBlock(self.blockstate_api.blockstateToID(name, properties))
                if block is not None:
                    return block
            raise KeyError("No blocks named: " + key)
        if isinstance(key, (tuple, list)):
            block_id, blockData = key
            return self.blockWithID(block_id, blockData)
        return self.blockWithID(key)

    @property
    def terrainTexture(self):
        if hasattr(self, "_terrainTexture"):
            return self._terrainTexture
        return namedMaterials[self.name]._terrainTexture

    @terrainTexture.setter
    def terrainTexture(self, value):
        self._terrainTexture = value

    def blocksMatching(self, name, names=None):
        toReturn = []
        name = name.lower()
        spiltNames = name.split(" ")
        amount = len(spiltNames)
        for i, v in enumerate(self.allBlocks):
            if names is None:
                nameParts = v.name.lower().split(" ")
                for anotherName in v.aka.lower().split(" "):
                    nameParts.append(anotherName)
                for anotherName in v.search.lower().split(" "):
                    nameParts.append(anotherName)
            else:
                nameParts = names[i].lower().split(" ")
            i = 0
            spiltNamesUsed = []
            for v2 in nameParts:
                Start = True
                j = 0
                while j < len(spiltNames) and Start:
                    if spiltNames[j] in v2 and j not in spiltNamesUsed:
                        i += 1
                        spiltNamesUsed.append(j)
                        Start = False
                    j += 1
            if i == amount:
                toReturn.append(v)
        return toReturn

    def blockWithID(self, block_id, data=0):
        if (block_id, data) in self.blocksByID:
            return self.blocksByID[block_id, data]
        else:
            bl = Block(self, block_id, blockData=data)
            return bl

    def addJSONBlocksFromFile(self, filename):
        blockyaml = None
        try:
            f = pkg_resources.resource_stream(__name__, filename)
        except (ImportError, IOError) as e:
            log.debug("Cannot get resource_stream for %s %s" % (filename, e))
            root = os.environ.get("PYMCLEVEL_YAML_ROOT", "pymclevel")  # fall back to cwd as last resort
            path = join(root, filename)

            log.debug("Failed to read %s using pkg_resources. Trying %s instead." % (filename, path))

            # pcm1k - does this leak?
            f = file(path)
        try:
            log.info(u"Loading block info from %s", f)
            blockyaml = json.load(f)

        except Exception as e:
            log.warn(u"Exception while loading block info from %s: %s", f, e)
            traceback.print_exc()

        if blockyaml:
            self.addJSONBlocks(blockyaml)

    def addJSONBlocksFromVersion(self, platform, version):
        # Load first the versioned stuff
        log.debug("Loading block definitions from versioned file")
        print "Game Version: {} : {}".format(platform, version)
        self.defsIds = get_defs_ids(platform, version, checkTimes=False)
        self.addJSONBlocks(self.defsIds.jsonDict)
        self.blockstate_api._initBlockMap()
        build_materials(self, platform)

    def addJSONBlocks(self, blockyaml):
        self.yamlDatas.append(blockyaml)
        for block in blockyaml['blocks']:
            try:
                self.addJSONBlock(block)
            except Exception as e:
                log.warn(u"Exception while parsing block: %s", e)
                traceback.print_exc()
                log.warn(u"Block definition: \n%s", pformat(block))

    def addJSONBlock(self, kw):
        blockID = kw['id']

        # xxx unused_yaml_properties variable unused; needed for
        # documentation purpose of some sort?  -zothar
        # unused_yaml_properties = \
        #['explored',
        # # 'id',
        # # 'idStr',
        # # 'mapcolor',
        # # 'name',
        # # 'tex',
        # ### 'tex_data',
        # # 'tex_direction',
        # ### 'tex_direction_data',
        # 'tex_extra',
        # # 'type'
        # ]

        for val, data in kw.get('data', {0: {}}).iteritems():
            datakw = dict(kw)
            datakw.update(data)
            tex = [t * 16 for t in datakw.get('tex', self.defaultTex)]
            texture = [tex] * 6
            texDirs = {
                "FORWARD": 5,
                "BACKWARD": 4,
                "LEFT": 1,
                "RIGHT": 0,
                "TOP": 2,
                "BOTTOM": 3,
            }
            for dirname, dirtex in datakw.get('tex_direction', {}).iteritems():
                if dirname == "SIDES":
                    for dirname in ("LEFT", "RIGHT"):
                        texture[texDirs[dirname]] = [t * 16 for t in dirtex]
                if dirname in texDirs:
                    texture[texDirs[dirname]] = [t * 16 for t in dirtex]
            datakw['texture'] = texture
            # print datakw
            block = self.addBlock(blockID, val, **datakw)
            block.yaml = datakw

        tex_direction_data = kw.get('tex_direction_data')
        if tex_direction_data:
            texture = datakw['texture']
            # X+0, X-1, Y+, Y-, Z+b, Z-f
            texDirMap = {
                "NORTH": 0,
                "EAST": 1,
                "SOUTH": 2,
                "WEST": 3,
            }

            def rot90cw():
                rot = (5, 0, 2, 3, 4, 1)
                texture[:] = [texture[r] for r in rot]

            for data, direction in tex_direction_data.iteritems():
                for _i in xrange(texDirMap.get(direction, 0)):
                    rot90cw()
                self.blockTextures[blockID][int(data)] = texture

    def addBlock(self, blockID, blockData=0, **kw):
        blockData = int(blockData)
        try:
            name = kw.pop('name', self.names[blockID][blockData])
        except:
            print (blockID, blockData)
        stringName = kw.pop('idStr', '')
        namespace = kw.pop("namespace", "minecraft")
        properties = kw.pop("properties", {})

        self.lightEmission[blockID] = kw.pop('brightness', self.defaultBrightness)
        self.lightAbsorption[blockID] = kw.pop('opacity', self.defaultOpacity)
        self.aka[blockID][blockData] = kw.pop('aka', "")
        self.search[blockID][blockData] = kw.pop('search', "")
        block_type = kw.pop('type', 'NORMAL')

        color = kw.pop('mapcolor', self.flatColors[blockID, blockData])
        self.flatColors[blockID, blockData] = (tuple(color) + (255,))[:4]

        texture = kw.pop('texture', None)

        if texture:
            self.blockTextures[blockID, blockData] = texture

        self.names[blockID][blockData] = name
        if blockData is 0:
            self.type[blockID] = [block_type] * data_limit
        else:
            self.type[blockID][blockData] = block_type

        block = Block(self, blockID, blockData)

        if kw.pop('invalid', 'false') == 'false':
            # the reason there is an "invalid" property (taken from minecraft.yaml):
            # the following only exist inside MCEdits rendering system
            # to represent door states that aren't encoded into minecraft's
            # metadata like (Upper, Left Hinge, Closed, East)
            self.allBlocks.append(block)
            self.idStr[blockID] = stringName
            self.namespace[blockID] = namespace
            self.properties[blockID][blockData] = properties
        self.blocksByType[block_type].append(block)

        self.blocksByID[blockID, blockData] = block

        return block


# --- Static block defs ---

def build_alpha_materials(alphaMaterials):
    log.info("Building Alpha materials.")
    alphaMaterials.Stone = alphaMaterials[1, 0]
    alphaMaterials.Grass = alphaMaterials[2, 0]
    alphaMaterials.Dirt = alphaMaterials[3, 0]
    alphaMaterials.Cobblestone = alphaMaterials[4, 0]
    alphaMaterials.WoodPlanks = alphaMaterials[5, 0]
    alphaMaterials.Sapling = alphaMaterials[6, 0]
    alphaMaterials.SpruceSapling = alphaMaterials[6, 1]
    alphaMaterials.BirchSapling = alphaMaterials[6, 2]
    alphaMaterials.Bedrock = alphaMaterials[7, 0]
    alphaMaterials.WaterActive = alphaMaterials[8, 0]
    alphaMaterials.Water = alphaMaterials[9, 0]
    alphaMaterials.LavaActive = alphaMaterials[10, 0]
    alphaMaterials.Lava = alphaMaterials[11, 0]
    alphaMaterials.Sand = alphaMaterials[12, 0]
    alphaMaterials.Gravel = alphaMaterials[13, 0]
    alphaMaterials.GoldOre = alphaMaterials[14, 0]
    alphaMaterials.IronOre = alphaMaterials[15, 0]
    alphaMaterials.CoalOre = alphaMaterials[16, 0]
    alphaMaterials.Wood = alphaMaterials[17, 0]
    alphaMaterials.PineWood = alphaMaterials[17, 1]
    alphaMaterials.BirchWood = alphaMaterials[17, 2]
    alphaMaterials.JungleWood = alphaMaterials[17, 3]
    alphaMaterials.Leaves = alphaMaterials[18, 0]
    alphaMaterials.PineLeaves = alphaMaterials[18, 1]
    alphaMaterials.BirchLeaves = alphaMaterials[18, 2]
    alphaMaterials.JungleLeaves = alphaMaterials[18, 3]
    alphaMaterials.LeavesPermanent = alphaMaterials[18, 4]
    alphaMaterials.PineLeavesPermanent = alphaMaterials[18, 5]
    alphaMaterials.BirchLeavesPermanent = alphaMaterials[18, 6]
    alphaMaterials.JungleLeavesPermanent = alphaMaterials[18, 7]
    alphaMaterials.LeavesDecaying = alphaMaterials[18, 8]
    alphaMaterials.PineLeavesDecaying = alphaMaterials[18, 9]
    alphaMaterials.BirchLeavesDecaying = alphaMaterials[18, 10]
    alphaMaterials.JungleLeavesDecaying = alphaMaterials[18, 11]
    alphaMaterials.Sponge = alphaMaterials[19, 0]
    alphaMaterials.Glass = alphaMaterials[20, 0]
    alphaMaterials.LapisLazuliOre = alphaMaterials[21, 0]
    alphaMaterials.LapisLazuliBlock = alphaMaterials[22, 0]
    alphaMaterials.Dispenser = alphaMaterials[23, 0]
    alphaMaterials.Sandstone = alphaMaterials[24, 0]
    alphaMaterials.NoteBlock = alphaMaterials[25, 0]
    alphaMaterials.Bed = alphaMaterials[26, 0]
    alphaMaterials.PoweredRail = alphaMaterials[27, 0]
    alphaMaterials.DetectorRail = alphaMaterials[28, 0]
    alphaMaterials.StickyPiston = alphaMaterials[29, 0]
    alphaMaterials.Web = alphaMaterials[30, 0]
    alphaMaterials.UnusedShrub = alphaMaterials[31, 0]
    alphaMaterials.TallGrass = alphaMaterials[31, 1]
    alphaMaterials.Shrub = alphaMaterials[31, 2]
    alphaMaterials.DesertShrub2 = alphaMaterials[32, 0]
    alphaMaterials.Piston = alphaMaterials[33, 0]
    alphaMaterials.PistonHead = alphaMaterials[34, 0]
    alphaMaterials.WhiteWool = alphaMaterials[35, 0]
    alphaMaterials.OrangeWool = alphaMaterials[35, 1]
    alphaMaterials.MagentaWool = alphaMaterials[35, 2]
    alphaMaterials.LightBlueWool = alphaMaterials[35, 3]
    alphaMaterials.YellowWool = alphaMaterials[35, 4]
    alphaMaterials.LightGreenWool = alphaMaterials[35, 5]
    alphaMaterials.PinkWool = alphaMaterials[35, 6]
    alphaMaterials.GrayWool = alphaMaterials[35, 7]
    alphaMaterials.LightGrayWool = alphaMaterials[35, 8]
    alphaMaterials.CyanWool = alphaMaterials[35, 9]
    alphaMaterials.PurpleWool = alphaMaterials[35, 10]
    alphaMaterials.BlueWool = alphaMaterials[35, 11]
    alphaMaterials.BrownWool = alphaMaterials[35, 12]
    alphaMaterials.DarkGreenWool = alphaMaterials[35, 13]
    alphaMaterials.RedWool = alphaMaterials[35, 14]
    alphaMaterials.BlackWool = alphaMaterials[35, 15]
    alphaMaterials.Block36 = alphaMaterials[36, 0]
    alphaMaterials.Flower = alphaMaterials[37, 0]
    alphaMaterials.Rose = alphaMaterials[38, 0]
    alphaMaterials.BrownMushroom = alphaMaterials[39, 0]
    alphaMaterials.RedMushroom = alphaMaterials[40, 0]
    alphaMaterials.BlockofGold = alphaMaterials[41, 0]
    alphaMaterials.BlockofIron = alphaMaterials[42, 0]
    alphaMaterials.DoubleStoneSlab = alphaMaterials[43, 0]
    alphaMaterials.DoubleSandstoneSlab = alphaMaterials[43, 1]
    alphaMaterials.DoubleWoodenSlab = alphaMaterials[43, 2]
    alphaMaterials.DoubleCobblestoneSlab = alphaMaterials[43, 3]
    alphaMaterials.DoubleBrickSlab = alphaMaterials[43, 4]
    alphaMaterials.DoubleStoneBrickSlab = alphaMaterials[43, 5]
    alphaMaterials.StoneSlab = alphaMaterials[44, 0]
    alphaMaterials.SandstoneSlab = alphaMaterials[44, 1]
    alphaMaterials.WoodenSlab = alphaMaterials[44, 2]
    alphaMaterials.CobblestoneSlab = alphaMaterials[44, 3]
    alphaMaterials.BrickSlab = alphaMaterials[44, 4]
    alphaMaterials.StoneBrickSlab = alphaMaterials[44, 5]
    alphaMaterials.Brick = alphaMaterials[45, 0]
    alphaMaterials.TNT = alphaMaterials[46, 0]
    alphaMaterials.Bookshelf = alphaMaterials[47, 0]
    alphaMaterials.MossStone = alphaMaterials[48, 0]
    alphaMaterials.Obsidian = alphaMaterials[49, 0]
    alphaMaterials.Torch = alphaMaterials[50, 0]
    alphaMaterials.Fire = alphaMaterials[51, 0]
    alphaMaterials.MonsterSpawner = alphaMaterials[52, 0]
    alphaMaterials.WoodenStairs = alphaMaterials[53, 0]
    alphaMaterials.Chest = alphaMaterials[54, 0]
    alphaMaterials.RedstoneWire = alphaMaterials[55, 0]
    alphaMaterials.DiamondOre = alphaMaterials[56, 0]
    alphaMaterials.BlockofDiamond = alphaMaterials[57, 0]
    alphaMaterials.CraftingTable = alphaMaterials[58, 0]
    alphaMaterials.Crops = alphaMaterials[59, 0]
    alphaMaterials.Farmland = alphaMaterials[60, 0]
    alphaMaterials.Furnace = alphaMaterials[61, 0]
    alphaMaterials.LitFurnace = alphaMaterials[62, 0]
    alphaMaterials.Sign = alphaMaterials[63, 0]
    alphaMaterials.WoodenDoor = alphaMaterials[64, 0]
    alphaMaterials.Ladder = alphaMaterials[65, 0]
    alphaMaterials.Rail = alphaMaterials[66, 0]
    alphaMaterials.StoneStairs = alphaMaterials[67, 0]
    alphaMaterials.WallSign = alphaMaterials[68, 0]
    alphaMaterials.Lever = alphaMaterials[69, 0]
    alphaMaterials.StoneFloorPlate = alphaMaterials[70, 0]
    alphaMaterials.IronDoor = alphaMaterials[71, 0]
    alphaMaterials.WoodFloorPlate = alphaMaterials[72, 0]
    alphaMaterials.RedstoneOre = alphaMaterials[73, 0]
    alphaMaterials.RedstoneOreGlowing = alphaMaterials[74, 0]
    alphaMaterials.RedstoneTorchOff = alphaMaterials[75, 0]
    alphaMaterials.RedstoneTorchOn = alphaMaterials[76, 0]
    alphaMaterials.Button = alphaMaterials[77, 0]
    alphaMaterials.SnowLayer = alphaMaterials[78, 0]
    alphaMaterials.Ice = alphaMaterials[79, 0]
    alphaMaterials.Snow = alphaMaterials[80, 0]
    alphaMaterials.Cactus = alphaMaterials[81, 0]
    alphaMaterials.Clay = alphaMaterials[82, 0]
    alphaMaterials.SugarCane = alphaMaterials[83, 0]
    alphaMaterials.Jukebox = alphaMaterials[84, 0]
    alphaMaterials.Fence = alphaMaterials[85, 0]
    alphaMaterials.Pumpkin = alphaMaterials[86, 0]
    alphaMaterials.Netherrack = alphaMaterials[87, 0]
    alphaMaterials.SoulSand = alphaMaterials[88, 0]
    alphaMaterials.Glowstone = alphaMaterials[89, 0]
    alphaMaterials.NetherPortal = alphaMaterials[90, 0]
    alphaMaterials.JackOLantern = alphaMaterials[91, 0]
    alphaMaterials.Cake = alphaMaterials[92, 0]
    alphaMaterials.RedstoneRepeaterOff = alphaMaterials[93, 0]
    alphaMaterials.RedstoneRepeaterOn = alphaMaterials[94, 0]
    alphaMaterials.StainedGlass = alphaMaterials[95, 0]
    alphaMaterials.Trapdoor = alphaMaterials[96, 0]
    alphaMaterials.HiddenSilverfishStone = alphaMaterials[97, 0]
    alphaMaterials.HiddenSilverfishCobblestone = alphaMaterials[97, 1]
    alphaMaterials.HiddenSilverfishStoneBrick = alphaMaterials[97, 2]
    alphaMaterials.StoneBricks = alphaMaterials[98, 0]
    alphaMaterials.MossyStoneBricks = alphaMaterials[98, 1]
    alphaMaterials.CrackedStoneBricks = alphaMaterials[98, 2]
    alphaMaterials.HugeBrownMushroom = alphaMaterials[99, 0]
    alphaMaterials.HugeRedMushroom = alphaMaterials[100, 0]
    alphaMaterials.IronBars = alphaMaterials[101, 0]
    alphaMaterials.GlassPane = alphaMaterials[102, 0]
    alphaMaterials.Watermelon = alphaMaterials[103, 0]
    alphaMaterials.PumpkinStem = alphaMaterials[104, 0]
    alphaMaterials.MelonStem = alphaMaterials[105, 0]
    alphaMaterials.Vines = alphaMaterials[106, 0]
    alphaMaterials.FenceGate = alphaMaterials[107, 0]
    alphaMaterials.BrickStairs = alphaMaterials[108, 0]
    alphaMaterials.StoneBrickStairs = alphaMaterials[109, 0]
    alphaMaterials.Mycelium = alphaMaterials[110, 0]
    alphaMaterials.Lilypad = alphaMaterials[111, 0]
    alphaMaterials.NetherBrick = alphaMaterials[112, 0]
    alphaMaterials.NetherBrickFence = alphaMaterials[113, 0]
    alphaMaterials.NetherBrickStairs = alphaMaterials[114, 0]
    alphaMaterials.NetherWart = alphaMaterials[115, 0]
    alphaMaterials.EnchantmentTable = alphaMaterials[116, 0]
    alphaMaterials.BrewingStand = alphaMaterials[117, 0]
    alphaMaterials.Cauldron = alphaMaterials[118, 0]
    alphaMaterials.EnderPortal = alphaMaterials[119, 0]
    alphaMaterials.PortalFrame = alphaMaterials[120, 0]
    alphaMaterials.EndStone = alphaMaterials[121, 0]
    alphaMaterials.DragonEgg = alphaMaterials[122, 0]
    alphaMaterials.RedstoneLampoff = alphaMaterials[123, 0]
    alphaMaterials.RedstoneLampon = alphaMaterials[124, 0]
    alphaMaterials.OakWoodDoubleSlab = alphaMaterials[125, 0]
    alphaMaterials.SpruceWoodDoubleSlab = alphaMaterials[125, 1]
    alphaMaterials.BirchWoodDoubleSlab = alphaMaterials[125, 2]
    alphaMaterials.JungleWoodDoubleSlab = alphaMaterials[125, 3]
    alphaMaterials.OakWoodSlab = alphaMaterials[126, 0]
    alphaMaterials.SpruceWoodSlab = alphaMaterials[126, 1]
    alphaMaterials.BirchWoodSlab = alphaMaterials[126, 2]
    alphaMaterials.JungleWoodSlab = alphaMaterials[126, 3]
    alphaMaterials.CocoaPlant = alphaMaterials[127, 0]
    alphaMaterials.SandstoneStairs = alphaMaterials[128, 0]
    alphaMaterials.EmeraldOre = alphaMaterials[129, 0]
    alphaMaterials.EnderChest = alphaMaterials[130, 0]
    alphaMaterials.TripwireHook = alphaMaterials[131, 0]
    alphaMaterials.Tripwire = alphaMaterials[132, 0]
    alphaMaterials.BlockofEmerald = alphaMaterials[133, 0]
    alphaMaterials.SpruceWoodStairs = alphaMaterials[134, 0]
    alphaMaterials.BirchWoodStairs = alphaMaterials[135, 0]
    alphaMaterials.JungleWoodStairs = alphaMaterials[136, 0]
    alphaMaterials.CommandBlock = alphaMaterials[137, 0]
    alphaMaterials.BeaconBlock = alphaMaterials[138, 0]
    alphaMaterials.CobblestoneWall = alphaMaterials[139, 0]
    alphaMaterials.MossyCobblestoneWall = alphaMaterials[139, 1]
    alphaMaterials.FlowerPot = alphaMaterials[140, 0]
    alphaMaterials.Carrots = alphaMaterials[141, 0]
    alphaMaterials.Potatoes = alphaMaterials[142, 0]
    alphaMaterials.WoodenButton = alphaMaterials[143, 0]
    alphaMaterials.MobHead = alphaMaterials[144, 0]
    alphaMaterials.Anvil = alphaMaterials[145, 0]
    alphaMaterials.TrappedChest = alphaMaterials[146, 0]
    alphaMaterials.WeightedPressurePlateLight = alphaMaterials[147, 0]
    alphaMaterials.WeightedPressurePlateHeavy = alphaMaterials[148, 0]
    alphaMaterials.RedstoneComparatorInactive = alphaMaterials[149, 0]
    alphaMaterials.RedstoneComparatorActive = alphaMaterials[150, 0]
    alphaMaterials.DaylightSensor = alphaMaterials[151, 0]
    alphaMaterials.BlockofRedstone = alphaMaterials[152, 0]
    alphaMaterials.NetherQuartzOre = alphaMaterials[153, 0]
    alphaMaterials.Hopper = alphaMaterials[154, 0]
    alphaMaterials.BlockofQuartz = alphaMaterials[155, 0]
    alphaMaterials.QuartzStairs = alphaMaterials[156, 0]
    alphaMaterials.ActivatorRail = alphaMaterials[157, 0]
    alphaMaterials.Dropper = alphaMaterials[158, 0]
    alphaMaterials.StainedClay = alphaMaterials[159, 0]
    alphaMaterials.StainedGlassPane = alphaMaterials[160, 0]
    alphaMaterials.AcaciaLeaves = alphaMaterials[161, 0]
    alphaMaterials.DarkOakLeaves = alphaMaterials[161, 1]
    alphaMaterials.AcaciaLeavesPermanent = alphaMaterials[161, 4]
    alphaMaterials.DarkOakLeavesPermanent = alphaMaterials[161, 5]
    alphaMaterials.AcaciaLeavesDecaying = alphaMaterials[161, 8]
    alphaMaterials.DarkOakLeavesDecaying = alphaMaterials[161, 9]
    alphaMaterials.Wood2 = alphaMaterials[162, 0]
    alphaMaterials.AcaciaStairs = alphaMaterials[163, 0]
    alphaMaterials.DarkOakStairs = alphaMaterials[164, 0]
    alphaMaterials.SlimeBlock = alphaMaterials[165, 0]
    alphaMaterials.Barrier = alphaMaterials[166, 0]
    alphaMaterials.IronTrapdoor = alphaMaterials[167, 0]
    alphaMaterials.Prismarine = alphaMaterials[168, 0]
    alphaMaterials.SeaLantern = alphaMaterials[169, 0]
    alphaMaterials.HayBlock = alphaMaterials[170, 0]
    alphaMaterials.Carpet = alphaMaterials[171, 0]
    alphaMaterials.HardenedClay = alphaMaterials[172, 0]
    alphaMaterials.CoalBlock = alphaMaterials[173, 0]
    alphaMaterials.PackedIce = alphaMaterials[174, 0]
    alphaMaterials.TallFlowers = alphaMaterials[175, 0]
    alphaMaterials.StandingBanner = alphaMaterials[176, 0]
    alphaMaterials.WallBanner = alphaMaterials[177, 0]
    alphaMaterials.DaylightSensorOn = alphaMaterials[178, 0]
    alphaMaterials.RedSandstone = alphaMaterials[179, 0]
    alphaMaterials.SmooothRedSandstone = alphaMaterials[179, 1]
    alphaMaterials.RedSandstoneSairs = alphaMaterials[180, 0]
    alphaMaterials.DoubleRedSandstoneSlab = alphaMaterials[181, 0]
    alphaMaterials.RedSandstoneSlab = alphaMaterials[182, 0]
    alphaMaterials.SpruceFenceGate = alphaMaterials[183, 0]
    alphaMaterials.BirchFenceGate = alphaMaterials[184, 0]
    alphaMaterials.JungleFenceGate = alphaMaterials[185, 0]
    alphaMaterials.DarkOakFenceGate = alphaMaterials[186, 0]
    alphaMaterials.AcaciaFenceGate = alphaMaterials[187, 0]
    alphaMaterials.SpruceFence = alphaMaterials[188, 0]
    alphaMaterials.BirchFence = alphaMaterials[189, 0]
    alphaMaterials.JungleFence = alphaMaterials[190, 0]
    alphaMaterials.DarkOakFence = alphaMaterials[191, 0]
    alphaMaterials.AcaciaFence = alphaMaterials[192, 0]
    alphaMaterials.SpruceDoor = alphaMaterials[193, 0]
    alphaMaterials.BirchDoor = alphaMaterials[194, 0]
    alphaMaterials.JungleDoor = alphaMaterials[195, 0]
    alphaMaterials.AcaciaDoor = alphaMaterials[196, 0]
    alphaMaterials.DarkOakDoor = alphaMaterials[197, 0]
    alphaMaterials.EndRod = alphaMaterials[198, 0]
    alphaMaterials.ChorusPlant = alphaMaterials[199, 0]
    alphaMaterials.ChorusFlowerAlive = alphaMaterials[200, 0]
    alphaMaterials.ChorusFlowerDead = alphaMaterials[200, 5]
    alphaMaterials.Purpur = alphaMaterials[201, 0]
    alphaMaterials.PurpurPillar = alphaMaterials[202, 0]
    alphaMaterials.PurpurStairs = alphaMaterials[203, 0]
    alphaMaterials.PurpurSlab = alphaMaterials[205, 0]
    alphaMaterials.EndStone = alphaMaterials[206, 0]
    alphaMaterials.BeetRoot = alphaMaterials[207, 0]
    alphaMaterials.GrassPath = alphaMaterials[208, 0]
    alphaMaterials.EndGateway = alphaMaterials[209, 0]
    alphaMaterials.CommandBlockRepeating = alphaMaterials[210, 0]
    alphaMaterials.CommandBlockChain = alphaMaterials[211, 0]
    alphaMaterials.FrostedIce = alphaMaterials[212, 0]
    alphaMaterials.StructureVoid = alphaMaterials[217, 0]
    alphaMaterials.StructureBlock = alphaMaterials[255, 0]

# --- Classic static block defs ---
def build_classic_materials(classicMaterials):
    log.info("Building Classic materials.")
    classicMaterials.Stone = classicMaterials[1]
    classicMaterials.Grass = classicMaterials[2]
    classicMaterials.Dirt = classicMaterials[3]
    classicMaterials.Cobblestone = classicMaterials[4]
    classicMaterials.WoodPlanks = classicMaterials[5]
    classicMaterials.Sapling = classicMaterials[6]
    classicMaterials.Bedrock = classicMaterials[7]
    classicMaterials.WaterActive = classicMaterials[8]
    classicMaterials.Water = classicMaterials[9]
    classicMaterials.LavaActive = classicMaterials[10]
    classicMaterials.Lava = classicMaterials[11]
    classicMaterials.Sand = classicMaterials[12]
    classicMaterials.Gravel = classicMaterials[13]
    classicMaterials.GoldOre = classicMaterials[14]
    classicMaterials.IronOre = classicMaterials[15]
    classicMaterials.CoalOre = classicMaterials[16]
    classicMaterials.Wood = classicMaterials[17]
    classicMaterials.Leaves = classicMaterials[18]
    classicMaterials.Sponge = classicMaterials[19]
    classicMaterials.Glass = classicMaterials[20]

    classicMaterials.RedWool = classicMaterials[21]
    classicMaterials.OrangeWool = classicMaterials[22]
    classicMaterials.YellowWool = classicMaterials[23]
    classicMaterials.LimeWool = classicMaterials[24]
    classicMaterials.GreenWool = classicMaterials[25]
    classicMaterials.AquaWool = classicMaterials[26]
    classicMaterials.CyanWool = classicMaterials[27]
    classicMaterials.BlueWool = classicMaterials[28]
    classicMaterials.PurpleWool = classicMaterials[29]
    classicMaterials.IndigoWool = classicMaterials[30]
    classicMaterials.VioletWool = classicMaterials[31]
    classicMaterials.MagentaWool = classicMaterials[32]
    classicMaterials.PinkWool = classicMaterials[33]
    classicMaterials.BlackWool = classicMaterials[34]
    classicMaterials.GrayWool = classicMaterials[35]
    classicMaterials.WhiteWool = classicMaterials[36]

    classicMaterials.Flower = classicMaterials[37]
    classicMaterials.Rose = classicMaterials[38]
    classicMaterials.BrownMushroom = classicMaterials[39]
    classicMaterials.RedMushroom = classicMaterials[40]
    classicMaterials.BlockofGold = classicMaterials[41]
    classicMaterials.BlockofIron = classicMaterials[42]
    classicMaterials.DoubleStoneSlab = classicMaterials[43]
    classicMaterials.StoneSlab = classicMaterials[44]
    classicMaterials.Brick = classicMaterials[45]
    classicMaterials.TNT = classicMaterials[46]
    classicMaterials.Bookshelf = classicMaterials[47]
    classicMaterials.MossStone = classicMaterials[48]
    classicMaterials.Obsidian = classicMaterials[49]

# --- Indev static block defs ---
def build_indev_materials(indevMaterials):
    log.info("Building Indev materials.")
    indevMaterials.Stone = indevMaterials[1]
    indevMaterials.Grass = indevMaterials[2]
    indevMaterials.Dirt = indevMaterials[3]
    indevMaterials.Cobblestone = indevMaterials[4]
    indevMaterials.WoodPlanks = indevMaterials[5]
    indevMaterials.Sapling = indevMaterials[6]
    indevMaterials.Bedrock = indevMaterials[7]
    indevMaterials.WaterActive = indevMaterials[8]
    indevMaterials.Water = indevMaterials[9]
    indevMaterials.LavaActive = indevMaterials[10]
    indevMaterials.Lava = indevMaterials[11]
    indevMaterials.Sand = indevMaterials[12]
    indevMaterials.Gravel = indevMaterials[13]
    indevMaterials.GoldOre = indevMaterials[14]
    indevMaterials.IronOre = indevMaterials[15]
    indevMaterials.CoalOre = indevMaterials[16]
    indevMaterials.Wood = indevMaterials[17]
    indevMaterials.Leaves = indevMaterials[18]
    indevMaterials.Sponge = indevMaterials[19]
    indevMaterials.Glass = indevMaterials[20]

    indevMaterials.RedWool = indevMaterials[21]
    indevMaterials.OrangeWool = indevMaterials[22]
    indevMaterials.YellowWool = indevMaterials[23]
    indevMaterials.LimeWool = indevMaterials[24]
    indevMaterials.GreenWool = indevMaterials[25]
    indevMaterials.AquaWool = indevMaterials[26]
    indevMaterials.CyanWool = indevMaterials[27]
    indevMaterials.BlueWool = indevMaterials[28]
    indevMaterials.PurpleWool = indevMaterials[29]
    indevMaterials.IndigoWool = indevMaterials[30]
    indevMaterials.VioletWool = indevMaterials[31]
    indevMaterials.MagentaWool = indevMaterials[32]
    indevMaterials.PinkWool = indevMaterials[33]
    indevMaterials.BlackWool = indevMaterials[34]
    indevMaterials.GrayWool = indevMaterials[35]
    indevMaterials.WhiteWool = indevMaterials[36]

    indevMaterials.Flower = indevMaterials[37]
    indevMaterials.Rose = indevMaterials[38]
    indevMaterials.BrownMushroom = indevMaterials[39]
    indevMaterials.RedMushroom = indevMaterials[40]
    indevMaterials.BlockofGold = indevMaterials[41]
    indevMaterials.BlockofIron = indevMaterials[42]
    indevMaterials.DoubleStoneSlab = indevMaterials[43]
    indevMaterials.StoneSlab = indevMaterials[44]
    indevMaterials.Brick = indevMaterials[45]
    indevMaterials.TNT = indevMaterials[46]
    indevMaterials.Bookshelf = indevMaterials[47]
    indevMaterials.MossStone = indevMaterials[48]
    indevMaterials.Obsidian = indevMaterials[49]

    indevMaterials.Torch = indevMaterials[50, 0]
    indevMaterials.Fire = indevMaterials[51, 0]
    indevMaterials.InfiniteWater = indevMaterials[52, 0]
    indevMaterials.InfiniteLava = indevMaterials[53, 0]
    indevMaterials.Chest = indevMaterials[54, 0]
    indevMaterials.Cog = indevMaterials[55, 0]
    indevMaterials.DiamondOre = indevMaterials[56, 0]
    indevMaterials.BlockofDiamond = indevMaterials[57, 0]
    indevMaterials.CraftingTable = indevMaterials[58, 0]
    indevMaterials.Crops = indevMaterials[59, 0]
    indevMaterials.Farmland = indevMaterials[60, 0]
    indevMaterials.Furnace = indevMaterials[61, 0]
    indevMaterials.LitFurnace = indevMaterials[62, 0]

# --- Pocket static block defs ---
def build_pocket_materials(pocketMaterials):
    log.info("Building Pocket materials.")
    pocketMaterials.Air = pocketMaterials[0, 0]
    pocketMaterials.Stone = pocketMaterials[1, 0]
    pocketMaterials.Grass = pocketMaterials[2, 0]
    pocketMaterials.Dirt = pocketMaterials[3, 0]
    pocketMaterials.Cobblestone = pocketMaterials[4, 0]
    pocketMaterials.WoodPlanks = pocketMaterials[5, 0]
    pocketMaterials.Sapling = pocketMaterials[6, 0]
    pocketMaterials.SpruceSapling = pocketMaterials[6, 1]
    pocketMaterials.BirchSapling = pocketMaterials[6, 2]
    pocketMaterials.Bedrock = pocketMaterials[7, 0]
    pocketMaterials.Wateractive = pocketMaterials[8, 0]
    pocketMaterials.Water = pocketMaterials[9, 0]
    pocketMaterials.Lavaactive = pocketMaterials[10, 0]
    pocketMaterials.Lava = pocketMaterials[11, 0]
    pocketMaterials.Sand = pocketMaterials[12, 0]
    pocketMaterials.Gravel = pocketMaterials[13, 0]
    pocketMaterials.GoldOre = pocketMaterials[14, 0]
    pocketMaterials.IronOre = pocketMaterials[15, 0]
    pocketMaterials.CoalOre = pocketMaterials[16, 0]

    pocketMaterials.Wood = pocketMaterials[17, 0]
    pocketMaterials.PineWood = pocketMaterials[17, 1]
    pocketMaterials.BirchWood = pocketMaterials[17, 2]
    pocketMaterials.JungleWood = pocketMaterials[17, 3]
    pocketMaterials.Leaves = pocketMaterials[18, 0]
    pocketMaterials.PineLeaves = pocketMaterials[18, 1]
    pocketMaterials.BirchLeaves = pocketMaterials[18, 2]
    pocketMaterials.JungleLeaves = pocketMaterials[18, 3]

    pocketMaterials.Sponge = pocketMaterials[19, 0]
    pocketMaterials.Glass = pocketMaterials[20, 0]

    pocketMaterials.LapisLazuliOre = pocketMaterials[21, 0]
    pocketMaterials.LapisLazuliBlock = pocketMaterials[22, 0]
    pocketMaterials.Sandstone = pocketMaterials[24, 0]
    pocketMaterials.NoteBlock = pocketMaterials[25, 0]
    pocketMaterials.Bed = pocketMaterials[26, 0]
    pocketMaterials.PoweredRail = pocketMaterials[27, 0]
    pocketMaterials.DetectorRail = pocketMaterials[28, 0]
    pocketMaterials.Web = pocketMaterials[30, 0]
    pocketMaterials.UnusedShrub = pocketMaterials[31, 0]
    pocketMaterials.TallGrass = pocketMaterials[31, 1]
    pocketMaterials.Shrub = pocketMaterials[31, 2]

    pocketMaterials.WhiteWool = pocketMaterials[35, 0]
    pocketMaterials.OrangeWool = pocketMaterials[35, 1]
    pocketMaterials.MagentaWool = pocketMaterials[35, 2]
    pocketMaterials.LightBlueWool = pocketMaterials[35, 3]
    pocketMaterials.YellowWool = pocketMaterials[35, 4]
    pocketMaterials.LightGreenWool = pocketMaterials[35, 5]
    pocketMaterials.PinkWool = pocketMaterials[35, 6]
    pocketMaterials.GrayWool = pocketMaterials[35, 7]
    pocketMaterials.LightGrayWool = pocketMaterials[35, 8]
    pocketMaterials.CyanWool = pocketMaterials[35, 9]
    pocketMaterials.PurpleWool = pocketMaterials[35, 10]
    pocketMaterials.BlueWool = pocketMaterials[35, 11]
    pocketMaterials.BrownWool = pocketMaterials[35, 12]
    pocketMaterials.DarkGreenWool = pocketMaterials[35, 13]
    pocketMaterials.RedWool = pocketMaterials[35, 14]
    pocketMaterials.BlackWool = pocketMaterials[35, 15]

    pocketMaterials.Flower = pocketMaterials[37, 0]
    pocketMaterials.Rose = pocketMaterials[38, 0]
    pocketMaterials.BrownMushroom = pocketMaterials[39, 0]
    pocketMaterials.RedMushroom = pocketMaterials[40, 0]
    pocketMaterials.BlockofGold = pocketMaterials[41, 0]
    pocketMaterials.BlockofIron = pocketMaterials[42, 0]

    pocketMaterials.DoubleStoneSlab = pocketMaterials[43, 0]
    pocketMaterials.DoubleSandstoneSlab = pocketMaterials[43, 1]
    pocketMaterials.DoubleWoodenSlab = pocketMaterials[43, 2]
    pocketMaterials.DoubleCobblestoneSlab = pocketMaterials[43, 3]
    pocketMaterials.DoubleBrickSlab = pocketMaterials[43, 4]
    pocketMaterials.StoneSlab = pocketMaterials[44, 0]
    pocketMaterials.SandstoneSlab = pocketMaterials[44, 1]
    pocketMaterials.WoodenSlab = pocketMaterials[44, 2]
    pocketMaterials.CobblestoneSlab = pocketMaterials[44, 3]
    pocketMaterials.BrickSlab = pocketMaterials[44, 4]

    pocketMaterials.Brick = pocketMaterials[45, 0]
    pocketMaterials.TNT = pocketMaterials[46, 0]
    pocketMaterials.Bookshelf = pocketMaterials[47, 0]
    pocketMaterials.MossStone = pocketMaterials[48, 0]
    pocketMaterials.Obsidian = pocketMaterials[49, 0]

    pocketMaterials.Torch = pocketMaterials[50, 0]
    pocketMaterials.Fire = pocketMaterials[51, 0]
    pocketMaterials.MonsterSpawner = pocketMaterials[52, 0]
    pocketMaterials.WoodenStairs = pocketMaterials[53, 0]
    pocketMaterials.Chest = pocketMaterials[54, 0]
    pocketMaterials.RedstoneWire = pocketMaterials[55, 0]
    pocketMaterials.DiamondOre = pocketMaterials[56, 0]
    pocketMaterials.BlockofDiamond = pocketMaterials[57, 0]
    pocketMaterials.CraftingTable = pocketMaterials[58, 0]
    pocketMaterials.Crops = pocketMaterials[59, 0]
    pocketMaterials.Farmland = pocketMaterials[60, 0]
    pocketMaterials.Furnace = pocketMaterials[61, 0]
    pocketMaterials.LitFurnace = pocketMaterials[62, 0]
    pocketMaterials.Sign = pocketMaterials[63, 0]
    pocketMaterials.WoodenDoor = pocketMaterials[64, 0]
    pocketMaterials.Ladder = pocketMaterials[65, 0]
    pocketMaterials.Rail = pocketMaterials[66, 0]
    pocketMaterials.StoneStairs = pocketMaterials[67, 0]
    pocketMaterials.WallSign = pocketMaterials[68, 0]
    pocketMaterials.Lever = pocketMaterials[69, 0]
    pocketMaterials.StoneFloorPlate = pocketMaterials[70, 0]
    pocketMaterials.IronDoor = pocketMaterials[71, 0]
    pocketMaterials.WoodFloorPlate = pocketMaterials[72, 0]
    pocketMaterials.RedstoneOre = pocketMaterials[73, 0]
    pocketMaterials.RedstoneOreGlowing = pocketMaterials[74, 0]
    pocketMaterials.RedstoneTorchOff = pocketMaterials[75, 0]
    pocketMaterials.RedstoneTorchOn = pocketMaterials[76, 0]
    pocketMaterials.Button = pocketMaterials[77, 0]
    pocketMaterials.SnowLayer = pocketMaterials[78, 0]
    pocketMaterials.Ice = pocketMaterials[79, 0]

    pocketMaterials.Snow = pocketMaterials[80, 0]
    pocketMaterials.Cactus = pocketMaterials[81, 0]
    pocketMaterials.Clay = pocketMaterials[82, 0]
    pocketMaterials.SugarCane = pocketMaterials[83, 0]
    pocketMaterials.Fence = pocketMaterials[85, 0]
    pocketMaterials.Pumpkin = pocketMaterials[86, 0]
    pocketMaterials.Netherrack = pocketMaterials[87, 0]
    pocketMaterials.SoulSand = pocketMaterials[88, 0]
    pocketMaterials.Glowstone = pocketMaterials[89, 0]
    pocketMaterials.NetherPortal = pocketMaterials[90, 0]
    pocketMaterials.JackOLantern = pocketMaterials[91, 0]
    pocketMaterials.Cake = pocketMaterials[92, 0]
    pocketMaterials.InvisibleBedrock = pocketMaterials[95, 0]
    pocketMaterials.Trapdoor = pocketMaterials[96, 0]

    pocketMaterials.MonsterEgg = pocketMaterials[97, 0]
    pocketMaterials.StoneBricks = pocketMaterials[98, 0]
    pocketMaterials.BrownMushroom = pocketMaterials[99, 0]
    pocketMaterials.RedMushroom = pocketMaterials[100, 0]
    pocketMaterials.IronBars = pocketMaterials[101, 0]
    pocketMaterials.GlassPane = pocketMaterials[102, 0]
    pocketMaterials.Watermelon = pocketMaterials[103, 0]
    pocketMaterials.PumpkinStem = pocketMaterials[104, 0]
    pocketMaterials.MelonStem = pocketMaterials[105, 0]
    pocketMaterials.Vines = pocketMaterials[106, 0]
    pocketMaterials.FenceGate = pocketMaterials[107, 0]
    pocketMaterials.BrickStairs = pocketMaterials[108, 0]
    pocketMaterials.StoneBrickStairs = pocketMaterials[109, 0]
    pocketMaterials.Mycelium = pocketMaterials[110, 0]
    pocketMaterials.Lilypad = pocketMaterials[111, 0]

    pocketMaterials.NetherBrick = pocketMaterials[112, 0]
    pocketMaterials.NetherBrickFence = pocketMaterials[113, 0]
    pocketMaterials.NetherBrickStairs = pocketMaterials[114, 0]
    pocketMaterials.NetherWart = pocketMaterials[115, 0]

    pocketMaterials.EnchantmentTable = pocketMaterials[116, 0]
    pocketMaterials.BrewingStand = pocketMaterials[117, 0]
    pocketMaterials.EndPortalFrame = pocketMaterials[120, 0]
    pocketMaterials.EndStone = pocketMaterials[121, 0]
    pocketMaterials.RedstoneLampoff = pocketMaterials[122, 0]
    pocketMaterials.RedstoneLampon = pocketMaterials[123, 0]
    pocketMaterials.ActivatorRail = pocketMaterials[126, 0]
    pocketMaterials.Cocoa = pocketMaterials[127, 0]
    pocketMaterials.SandstoneStairs = pocketMaterials[128, 0]
    pocketMaterials.EmeraldOre = pocketMaterials[129, 0]
    pocketMaterials.TripwireHook = pocketMaterials[131, 0]
    pocketMaterials.Tripwire = pocketMaterials[132, 0]
    pocketMaterials.BlockOfEmerald = pocketMaterials[133, 0]
    pocketMaterials.SpruceWoodStairs = pocketMaterials[134, 0]
    pocketMaterials.BirchWoodStairs = pocketMaterials[135, 0]
    pocketMaterials.JungleWoodStairs = pocketMaterials[136, 0]
    pocketMaterials.CommandBlock = pocketMaterials[137, 0]
    pocketMaterials.CobblestoneWall = pocketMaterials[139, 0]
    pocketMaterials.FlowerPot = pocketMaterials[140, 0]
    pocketMaterials.Carrots = pocketMaterials[141, 0]
    pocketMaterials.Potato = pocketMaterials[142, 0]
    pocketMaterials.WoodenButton = pocketMaterials[143, 0]
    pocketMaterials.MobHead = pocketMaterials[144, 0]
    pocketMaterials.Anvil = pocketMaterials[145, 0]
    pocketMaterials.TrappedChest = pocketMaterials[146, 0]
    pocketMaterials.WeightedPressurePlateLight = pocketMaterials[147, 0]
    pocketMaterials.WeightedPressurePlateHeavy = pocketMaterials[148, 0]
    pocketMaterials.DaylightSensor = pocketMaterials[151, 0]
    pocketMaterials.BlockOfRedstone = pocketMaterials[152, 0]
    pocketMaterials.NetherQuartzOre = pocketMaterials[153, 0]
    pocketMaterials.BlockOfQuartz = pocketMaterials[155, 0]
    pocketMaterials.DoubleWoodenSlab = pocketMaterials[157, 0]
    pocketMaterials.WoodenSlab = pocketMaterials[158, 0]
    pocketMaterials.StainedClay = pocketMaterials[159, 0]
    pocketMaterials.AcaciaLeaves = pocketMaterials[161, 0]
    pocketMaterials.AcaciaWood = pocketMaterials[162, 0]
    pocketMaterials.AcaciaWoodStairs = pocketMaterials[163, 0]
    pocketMaterials.DarkOakWoodStairs = pocketMaterials[164, 0]
    pocketMaterials.IronTrapdoor = pocketMaterials[167, 0]
    pocketMaterials.HayBale = pocketMaterials[170, 0]
    pocketMaterials.Carpet = pocketMaterials[171, 0]
    pocketMaterials.HardenedClay = pocketMaterials[172, 0]
    pocketMaterials.BlockOfCoal = pocketMaterials[173, 0]
    pocketMaterials.PackedIce = pocketMaterials[174, 0]
    # Is 'Sunflower' used?
    pocketMaterials.Sunflower = pocketMaterials[175, 0]
    pocketMaterials.TallFlowers = pocketMaterials[175, 0]
    pocketMaterials.DaylightSensorOn = pocketMaterials[178, 0]

    pocketMaterials.SpruceFenceGate = pocketMaterials[183, 0]
    pocketMaterials.BirchFenceGate = pocketMaterials[184, 0]
    pocketMaterials.JungleFenceGate = pocketMaterials[185, 0]
    pocketMaterials.DarkOakFenceGate = pocketMaterials[186, 0]
    pocketMaterials.AcaciaFenceGate = pocketMaterials[187, 0]
    pocketMaterials.CommandBlockRepeating = pocketMaterials[188, 0]
    pocketMaterials.CommandBlockChain = pocketMaterials[189, 0]
    pocketMaterials.GrassPath = pocketMaterials[198, 0]
    pocketMaterials.ItemFrame = pocketMaterials[199, 0]

    pocketMaterials.Podzol = pocketMaterials[243, 0]
    pocketMaterials.Beetroot = pocketMaterials[244, 0]
    pocketMaterials.StoneCutter = pocketMaterials[245, 0]
    pocketMaterials.GlowingObsidian = pocketMaterials[246, 0]
    pocketMaterials.NetherReactor = pocketMaterials[247, 0]
    pocketMaterials.NetherReactorUsed = pocketMaterials[247, 1]
    pocketMaterials.UpdateGameBlock1 = pocketMaterials[248, 0]
    pocketMaterials.UpdateGameBlock2 = pocketMaterials[249, 0]
    pocketMaterials.StructureBlock = pocketMaterials[252, 0]
    pocketMaterials.info_reserved6 = pocketMaterials[255, 0]

def build_materials(materials, platform):
    if platform == PLATFORM_ALPHA:
        build_alpha_materials(materials)
    elif platform == PLATFORM_CLASSIC:
        build_classic_materials(materials)
    elif platform == PLATFORM_INDEV:
        build_indev_materials(materials)
    elif platform == PLATFORM_POCKET:
        build_pocket_materials(materials)

def printStaticDefs(name, file_name=None):
    # printStaticDefs('alphaMaterials')
    # file_name: file to write the output to
    mats = eval(name)
    msg = "MCEdit static definitions for '%s'\n\n"%name
    mats_ids = []
    for b in sorted(mats.allBlocks):
        msg += "{name}.{0} = {name}[{1},{2}]\n".format(
            b.name.replace(" ", "").replace("(", "").replace(")", ""),
            b.ID, b.blockData,
            name=name,
        )
        if b.ID not in mats_ids:
            mats_ids.append(b.ID)
    print msg
    if file_name:
        msg += "\nNumber of materials: %s\n%s" % (len(mats_ids), mats_ids)
        id_min = min(mats_ids)
        id_max = max(mats_ids)
        msg += "\n\nLowest ID: %s\nHighest ID: %s\n" % (id_min, id_max)
        missing_ids = []
        for i in xrange(id_min, id_max + 1):
            if i not in mats_ids:
                missing_ids.append(i)
        if missing_ids:
                msg += "\nIDs not in the list:\n%s\n(%s IDs)\n" % (missing_ids, len(missing_ids))
        open(file_name, 'w').write(msg)
        print "Written to '%s'" % file_name


alphaMaterials = MCMaterials("Alpha", defaultName="Future Block!")
alphaMaterials.addJSONBlocksFromVersion(PLATFORM_ALPHA, VERSION_LATEST)

classicMaterials = MCMaterials("Classic", defaultName="Not present in Classic")
classicMaterials.addJSONBlocksFromVersion(PLATFORM_CLASSIC, VERSION_LATEST)

indevMaterials = MCMaterials("Indev", defaultName="Not present in Indev")
indevMaterials.addJSONBlocksFromVersion(PLATFORM_INDEV, VERSION_LATEST)

pocketMaterials = MCMaterials("Pocket", defaultName="Future Block!")
pocketMaterials.addJSONBlocksFromVersion(PLATFORM_POCKET, VERSION_LATEST)


_indices = rollaxis(indices((id_limit, data_limit)), 0, 3)


def _filterTable(filters, unavailable, default=(0, 0)):
    # a filter table is a id_limit table of (ID, data) pairs.
    table = zeros((id_limit, data_limit, 2), dtype='uint8')
    table[:] = _indices
    for u in unavailable:
        try:
            if u[1] == 0:
                u = u[0]
        except TypeError:
            pass
        table[u] = default
    for f, t in filters:
        try:
            if f[1] == 0:
                f = f[0]
        except TypeError:
            pass
        table[f] = t
    return table


nullConversion = lambda b, d: (b, d)


def filterConversion(table):
    def convert(blocks, data):
        if data is None:
            data = 0
        t = table[blocks, data]
        return t[..., 0], t[..., 1]

    return convert


def guessFilterTable(matsFrom, matsTo):
    """ Returns a pair (filters, unavailable)
    filters is a list of (from, to) pairs;  from and to are (ID, data) pairs
    unavailable is a list of (ID, data) pairs in matsFrom not found in matsTo.

    Searches the 'name' and 'aka' fields to find matches.
    """
    filters = []
    unavailable = []
    toByName = dict(((b.name, b) for b in sorted(matsTo.allBlocks, reverse=True)))
    for fromBlock in matsFrom.allBlocks:
        block = toByName.get(fromBlock.name)
        if block is None:
            for b in matsTo.allBlocks:
                if b.name.startswith(fromBlock.name):
                    block = b
                    break
        if block is None:
            for b in matsTo.allBlocks:
                if fromBlock.name in b.name:
                    block = b
                    break
        if block is None:
            for b in matsTo.allBlocks:
                if fromBlock.name in b.aka or fromBlock.name in b.search:
                    block = b
                    break
        if block is None:
            if "Indigo Wool" == fromBlock.name:
                block = toByName.get("Purple Wool")
            elif "Violet Wool" == fromBlock.name:
                block = toByName.get("Purple Wool")

        if block:
            if block != fromBlock:
                filters.append(((fromBlock.ID, fromBlock.blockData), (block.ID, block.blockData)))
        else:
            unavailable.append((fromBlock.ID, fromBlock.blockData))

    return filters, unavailable


allMaterials = (alphaMaterials, classicMaterials, pocketMaterials, indevMaterials)

_conversionFuncs = {}


def conversionFunc(destMats, sourceMats):
    if destMats is sourceMats:
        return nullConversion
    func = _conversionFuncs.get((destMats, sourceMats))
    if func:
        return func

    filters, unavailable = guessFilterTable(sourceMats, destMats)
    log.debug("")
    log.debug("%s %s %s", sourceMats.name, "=>", destMats.name)
    for a, b in [(sourceMats.blockWithID(*a), destMats.blockWithID(*b)) for a, b in filters]:
        log.debug("{0:20}: \"{1}\"".format('"' + a.name + '"', b.name))

    log.debug("")
    log.debug("Missing blocks: %s", [sourceMats.blockWithID(*a).name for a in unavailable])

    table = _filterTable(filters, unavailable, (35, 0))
    func = filterConversion(table)
    _conversionFuncs[(destMats, sourceMats)] = func
    return func


def convertBlocks(destMats, sourceMats, blocks, blockData):
    if sourceMats == destMats:
        return blocks, blockData

    return conversionFunc(destMats, sourceMats)(blocks, blockData)


namedMaterials = dict((i.name, i) for i in allMaterials)

_materialsCache = {}
#for mats in namedMaterials.itervalues():
#    if mats.defsIds.platform not in _materialsCache:
#        _materialsCache[mats.defsIds.platform] = {}
#    _materialsCache[mats.defsIds.platform][mats.defsIds.version] = mats

def _checkCache(platform, version, defsIds):
    if platform not in _materialsCache or version not in _materialsCache[platform]:
        return None
    materials = _materialsCache[platform][version]
    if materials.defsIds is not None and materials.defsIds is not defsIds:
        # different/outdated defsIds
        return None
    return materials

def getMaterialsByVer(platform, version, forceNew=False, **kwargs):
    defsIds = get_defs_ids(platform, version, checkTimes=False)
    return getMaterials(defsIds, forceNew=forceNew, **kwargs)

def getMaterials(defsIds, forceNew=False, **kwargs):
    """Creates a new MCMaterials object or retrieves one from the cache.
    forceNew will force a new object to be created, you should use this if you plan on potentially adding new blocks dynamically"""
    platform = defsIds.platform
    version = defsIds.version
    if forceNew:
        materials = MCMaterials(**kwargs)
    else:
        materials = _checkCache(platform, version, defsIds)
    if materials is not None:
        if materials.defsIds is None:
            # not initialized
            materials.addJSONBlocksFromVersion(platform, version)
        return materials

    materials = MCMaterials(**kwargs)
    materials.addJSONBlocksFromVersion(platform, version)

    if platform not in _materialsCache:
        _materialsCache[platform] = {}
    _materialsCache[platform][version] = materials

    return materials

__all__ = "indevMaterials, pocketMaterials, alphaMaterials, classicMaterials, namedMaterials, MCMaterials, BlockstateAPI".split(", ")


if '--dump-mats' in os.sys.argv:
    os.sys.argv.remove('--dump-mats')
    for n in ("indevMaterials", "pocketMaterials", "alphaMaterials", "classicMaterials"):
        printStaticDefs(n, "%s.mats" % n.split('M')[0])

# pcm1k - This is just some debug code I don't feel the need to update. Feel free to do it yourself if you really need it!
#if '--find-blockstates' in os.sys.argv:
#    pe_blockstates = {'minecraft': {}}
#    passed = []
#    failed = []
#    for block in pocketMaterials:
#        ID = block.ID
#        DATA = block.blockData
#        pc_block = alphaMaterials.get((ID, DATA))
#        if pc_block and pc_block.stringID == block.stringID:
#            passed.append(block)
#        else:
#            failed.append(block)
#    print '{} failed block check'.format(len(failed))
#    for block in failed:
#        print '!{}!'.format(block)
#    for block in passed:
#        if block.stringID not in pe_blockstates["minecraft"]:
#            pe_blockstates["minecraft"][block.stringID] = {}
#            pe_blockstates["minecraft"][block.stringID]["id"] = block.ID
#            pe_blockstates["minecraft"][block.stringID]["properties"] = []
#        blockstate = pocketMaterials.blockstate_api.idToBlockstate(block.ID, block.blockData)
#        state = {"<data>": block.blockData}
#        for (key, value) in blockstate[1].iteritems():
#            state[key] = value
#        pe_blockstates["minecraft"][block.stringID]['properties'].append(state)
