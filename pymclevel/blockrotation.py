from materials import alphaMaterials, id_limit, data_limit
from numpy import arange, zeros


class _AngleType(object):
    def __init__(self, name, toValueDict, requiredProps=None):
        self.name = name
        self.toValueDict = toValueDict
        self.toAngleDict = {propValue: angle for angle, propValue in toValueDict.iteritems()}
        self.requiredProps = requiredProps


_ANGLE_SOUTH = 0
_ANGLE_SOUTH_WEST = 2
_ANGLE_WEST = 4
_ANGLE_NORTH_WEST = 6
_ANGLE_NORTH = 8
_ANGLE_NORTH_EAST = 10
_ANGLE_EAST = 12
_ANGLE_SOUTH_EAST = 14

_ANGLE_DOWN = 0
_ANGLE_MIDDLE = 1
_ANGLE_UP = 2

_angleTypeList = [
    # TYPE_LEVER
    _AngleType(
        "facing",
        {
            (_ANGLE_SOUTH, _ANGLE_DOWN): "down_z",
            (_ANGLE_NORTH, _ANGLE_DOWN): "down_z",
            (_ANGLE_WEST, _ANGLE_DOWN): "down_x",
            (_ANGLE_EAST, _ANGLE_DOWN): "down_x",
            (_ANGLE_SOUTH, _ANGLE_MIDDLE): "south",
            (_ANGLE_WEST, _ANGLE_MIDDLE): "west",
            (_ANGLE_NORTH, _ANGLE_MIDDLE): "north",
            (_ANGLE_EAST, _ANGLE_MIDDLE): "east",
            (_ANGLE_SOUTH, _ANGLE_UP): "up_z",
            (_ANGLE_NORTH, _ANGLE_UP): "up_z",
            (_ANGLE_WEST, _ANGLE_UP): "up_x",
            (_ANGLE_EAST, _ANGLE_UP): "up_x",
        },
        requiredProps={"facing": {"down_x", "down_z", "up_x", "up_z"}}
    ),
    # TYPE_STAIRS
    _AngleType(
        ("facing", "half"),
        {
            (_ANGLE_SOUTH, _ANGLE_DOWN): ("south", "bottom"),
            (_ANGLE_WEST, _ANGLE_DOWN): ("west", "bottom"),
            (_ANGLE_NORTH, _ANGLE_DOWN): ("north", "bottom"),
            (_ANGLE_EAST, _ANGLE_DOWN): ("east", "bottom"),
            (_ANGLE_SOUTH, _ANGLE_UP): ("south", "top"),
            (_ANGLE_WEST, _ANGLE_UP): ("west", "top"),
            (_ANGLE_NORTH, _ANGLE_UP): ("north", "top"),
            (_ANGLE_EAST, _ANGLE_UP): ("east", "top"),
        }
    ),
    # TYPE_FACING
    _AngleType(
        "facing",
        {
            (_ANGLE_SOUTH, _ANGLE_DOWN): "down",
            (_ANGLE_WEST, _ANGLE_DOWN): "down",
            (_ANGLE_NORTH, _ANGLE_DOWN): "down",
            (_ANGLE_EAST, _ANGLE_DOWN): "down",
            (_ANGLE_SOUTH, _ANGLE_MIDDLE): "south",
            (_ANGLE_WEST, _ANGLE_MIDDLE): "west",
            (_ANGLE_NORTH, _ANGLE_MIDDLE): "north",
            (_ANGLE_EAST, _ANGLE_MIDDLE): "east",
            (_ANGLE_SOUTH, _ANGLE_UP): "up",
            (_ANGLE_WEST, _ANGLE_UP): "up",
            (_ANGLE_NORTH, _ANGLE_UP): "up",
            (_ANGLE_EAST, _ANGLE_UP): "up",
        }
    ),
    # TYPE_MUSHROOM
    _AngleType(
        "variant",
        {
            (_ANGLE_SOUTH, _ANGLE_MIDDLE): "south",
            (_ANGLE_SOUTH_WEST, _ANGLE_MIDDLE): "south_west",
            (_ANGLE_WEST, _ANGLE_MIDDLE): "west",
            (_ANGLE_NORTH_WEST, _ANGLE_MIDDLE): "north_west",
            (_ANGLE_NORTH, _ANGLE_MIDDLE): "north",
            (_ANGLE_NORTH_EAST, _ANGLE_MIDDLE): "north_east",
            (_ANGLE_EAST, _ANGLE_MIDDLE): "east",
            (_ANGLE_SOUTH_EAST, _ANGLE_MIDDLE): "south_east",
        }
    ),
    # TYPE_RAIL_UP
    _AngleType(
        "shape",
        {
            (_ANGLE_SOUTH, _ANGLE_MIDDLE): "ascending_south",
            (_ANGLE_WEST, _ANGLE_MIDDLE): "ascending_west",
            (_ANGLE_NORTH, _ANGLE_MIDDLE): "ascending_north",
            (_ANGLE_EAST, _ANGLE_MIDDLE): "ascending_east",
        }
    ),
    # TYPE_RAIL
    _AngleType(
        "shape",
        {
            (_ANGLE_SOUTH, _ANGLE_MIDDLE): "north_south",
            (_ANGLE_NORTH, _ANGLE_MIDDLE): "north_south",
            (_ANGLE_SOUTH_WEST, _ANGLE_MIDDLE): "south_west",
            (_ANGLE_WEST, _ANGLE_MIDDLE): "east_west",
            (_ANGLE_EAST, _ANGLE_MIDDLE): "east_west",
            (_ANGLE_NORTH_WEST, _ANGLE_MIDDLE): "north_west",
            (_ANGLE_NORTH_EAST, _ANGLE_MIDDLE): "north_east",
            (_ANGLE_SOUTH_EAST, _ANGLE_MIDDLE): "south_east",
        }
    ),
    # TYPE_SLAB
    _AngleType(
        "half",
        {
            (_ANGLE_SOUTH, _ANGLE_DOWN): "bottom",
            (_ANGLE_SOUTH, _ANGLE_UP): "top",
        }
    ),
    # TYPE_AXIS
    _AngleType(
        "axis",
        {
            (_ANGLE_SOUTH, _ANGLE_DOWN): "y",
            (_ANGLE_WEST, _ANGLE_DOWN): "y",
            (_ANGLE_NORTH, _ANGLE_DOWN): "y",
            (_ANGLE_EAST, _ANGLE_DOWN): "y",
            (_ANGLE_SOUTH, _ANGLE_MIDDLE): "z",
            (_ANGLE_NORTH, _ANGLE_MIDDLE): "z",
            (_ANGLE_WEST, _ANGLE_MIDDLE): "x",
            (_ANGLE_EAST, _ANGLE_MIDDLE): "x",
            (_ANGLE_SOUTH, _ANGLE_UP): "y",
            (_ANGLE_WEST, _ANGLE_UP): "y",
            (_ANGLE_NORTH, _ANGLE_UP): "y",
            (_ANGLE_EAST, _ANGLE_UP): "y",
        }
    ),
    # TYPE_AXIS_LINES
    _AngleType(
        "variant",
        {
            (_ANGLE_SOUTH, _ANGLE_DOWN): "lines_y",
            (_ANGLE_WEST, _ANGLE_DOWN): "lines_y",
            (_ANGLE_NORTH, _ANGLE_DOWN): "lines_y",
            (_ANGLE_EAST, _ANGLE_DOWN): "lines_y",
            (_ANGLE_SOUTH, _ANGLE_MIDDLE): "lines_z",
            (_ANGLE_NORTH, _ANGLE_MIDDLE): "lines_z",
            (_ANGLE_WEST, _ANGLE_MIDDLE): "lines_x",
            (_ANGLE_EAST, _ANGLE_MIDDLE): "lines_x",
            (_ANGLE_SOUTH, _ANGLE_UP): "lines_y",
            (_ANGLE_WEST, _ANGLE_UP): "lines_y",
            (_ANGLE_NORTH, _ANGLE_UP): "lines_y",
            (_ANGLE_EAST, _ANGLE_UP): "lines_y",
        }
    ),
]

_TYPE_LEVER = 0
_TYPE_STAIRS = 1
_TYPE_FACING = 2
_TYPE_MUSHROOM = 3
_TYPE_RAIL_UP = 4
_TYPE_RAIL = 5
_TYPE_SLAB = 6
_TYPE_AXIS = 7
_TYPE_AXIS_LINES = 8

# special cases
_TYPE_NUMBER = len(_angleTypeList)


def _getAngleFromSpecial(properties, allProps):
    rotation = properties.get("rotation")
    if rotation is not None:
        try:
            return (int(rotation), _ANGLE_MIDDLE), _TYPE_NUMBER
        except ValueError:
            return None
    return None


def _hasAllProps(allProps, propName, requiredProps):
    foundSet = set()
    for properties in allProps:
        if not bool(properties):
            continue
        # make sure propName exists
        propValue = properties.get(propName)
        if propValue is None:
#            continue
            return False
        # make sure all of requiredProps exists
        if propValue in requiredProps:
            foundSet.add(propValue)
        if len(foundSet) >= len(requiredProps):
            return True
    return False


def _checkRequiredProps(allProps, angleType):
    requiredProps = angleType.requiredProps
    if not bool(requiredProps):
        return True
    if not bool(allProps):
        return False
    for name, required in requiredProps.iteritems():
        if not _hasAllProps(allProps, name, required):
            return False
    return True


def _getPropValues(properties, allProps, angleType):
    propName = angleType.name
    if propName is None:
        return None
    if not _checkRequiredProps(allProps, angleType):
        return None

    if isinstance(propName, basestring):
        return properties.get(propName)
    # multiple names
    propValues = []
    for name in propName:
        value = properties.get(name)
        if value is None:
            return None
        propValues.append(value)
    return tuple(propValues)


def _getAngleFromProps(properties, allProps):
    angleFull = _getAngleFromSpecial(properties, allProps)
    if angleFull is not None:
        return angleFull

    # try to find the angle
    for angleIndex, angleType in enumerate(_angleTypeList):
        propValue = _getPropValues(properties, allProps, angleType)
        if propValue is None:
            continue
        angle = angleType.toAngleDict.get(propValue)
        if angle is not None:
            return angle, angleIndex
    return None


def _getPropsFromAngle(angle, angleIndex):
    # handle the special cases
    if angleIndex == _TYPE_NUMBER:
        if angle[1] == _ANGLE_MIDDLE:
            return {"rotation": str(angle[0])}
        return None

    angleType = _angleTypeList[angleIndex]
    propValue = angleType.toValueDict.get(angle)
    if propValue is None:
        return None

    if isinstance(propValue, basestring):
        return {angleType.name: propValue}
    # multiple names
    return dict(zip(angleType.name, propValue))


def _rotateLeftAngle(angle):
    return ((angle[0] - 4) & 15,) + angle[1:]


def _flipEastWestAngle(angle):
    return (-angle[0] & 15,) + angle[1:]


def _flipNorthSouthAngle(angle):
    return ((8 - angle[0]) & 15,) + angle[1:]


def _flipVerticalAngle(angle):
    return (angle[0], 2 - angle[1]) + angle[2:]

# "0": {"facing": "down",
# "1": {"facing": "up",
# "2": {"facing": "north",
# "3": {"facing": "south",
# "4": {"facing": "west"
# "5": {"facing": "east",
# Down = 0
# Up = 1
# East = 2
# West = 3
# North = 4
# South = 5
# rotation[cls.Up] = cls.North
# rotation[cls.Down] = cls.South
# rotation[cls.South] = cls.Up
# rotation[cls.North] = cls.Down
# rotation[up] = west
# rotation[down] = east
# rotation[east] = up
# rotation[west] = down

# "0": {"facing": "down_x",
# "1": {"facing": "east",
# "2": {"facing": "west",
# "3": {"facing": "south",
# "4": {"facing": "north",
# "5": {"facing": "up_z",
# "6": {"facing": "up_x",
# "7": {"facing": "down_z",
# DownSouth = 0
# South = 1
# North = 2
# West = 3
# East = 4
# UpSouth = 5
# UpWest = 6
# DownWest = 7
# Lever.roll[Lever.North] = Lever.DownSouth
# Lever.roll[Lever.South] = Lever.UpSouth
# Lever.roll[Lever.DownSouth] = Lever.South
# Lever.roll[Lever.DownWest] = Lever.South
# Lever.roll[Lever.UpSouth] = Lever.North
# Lever.roll[Lever.UpWest] = Lever.North
# Lever.roll[west] = down_x
# Lever.roll[east] = up_z
# Lever.roll[down_x] = east
# Lever.roll[down_z] = east
# Lever.roll[up_z] = west
# Lever.roll[up_x] = west

# "0": {"facing": "east",
# "1": {"facing": "west",
# "2": {"facing": "south",
# "3": {"facing": "north",
# "4": {"facing": "east_top",
# "5": {"facing": "west_top",
# "6": {"facing": "south_top",
# "7": {"facing": "north_top",
# South = 0
# North = 1
# West = 2
# East = 3
# TopSouth = 4
# TopNorth = 5
# TopWest = 6
# TopEast = 7
# Stair.roll[Stair.North] = Stair.South
# Stair.roll[Stair.South] = Stair.TopSouth
# Stair.roll[Stair.TopSouth] = Stair.TopNorth
# Stair.roll[Stair.TopNorth] = Stair.North
# Stair.roll[west] = east
# Stair.roll[east] = east_top
# Stair.roll[east_top] = west_top
# Stair.roll[west_top] = west
_stairsRollMap = {
    (_ANGLE_WEST, _ANGLE_DOWN): (_ANGLE_EAST, _ANGLE_DOWN),
    (_ANGLE_EAST, _ANGLE_DOWN): (_ANGLE_EAST, _ANGLE_UP),
    (_ANGLE_EAST, _ANGLE_UP): (_ANGLE_WEST, _ANGLE_UP),
    (_ANGLE_WEST, _ANGLE_UP): (_ANGLE_WEST, _ANGLE_DOWN),
}

# "1": {"variant": "north_west"
# "2": {"variant": "north"
# "3": {"variant": "north_east"
# "4": {"variant": "west"
# "6": {"variant": "east"
# "7": {"variant": "south_west"
# "8": {"variant": "south"
# "9": {"variant": "south_east"
# Northeast = 1
# East = 2
# Southeast = 3
# South = 6
# Southwest = 9
# West = 8
# Northwest = 7
# North = 4
# HugeMushroom.roll[HugeMushroom.Southeast] = HugeMushroom.Northeast
# HugeMushroom.roll[HugeMushroom.South] = HugeMushroom.North
# HugeMushroom.roll[HugeMushroom.Southwest] = HugeMushroom.Northwest
# HugeMushroom.roll[north_east] = north_west
# HugeMushroom.roll[east] = west
# HugeMushroom.roll[south_east] = south_west


def _rollAngle(angle, angleIndex):
    if angleIndex == _TYPE_STAIRS:
        newAngle = _stairsRollMap.get(angle)
        if newAngle is not None:
            return newAngle
        return angle
    if angleIndex in (_TYPE_MUSHROOM, _TYPE_RAIL_UP):
        return _flipEastWestAngle(angle)

    if angle[1] == _ANGLE_DOWN:
        # down -> east
        return (_ANGLE_EAST, _ANGLE_MIDDLE) + angle[2:]
    if angle[1] == _ANGLE_UP:
        # up -> west
        return (_ANGLE_WEST, _ANGLE_MIDDLE) + angle[2:]
    if angle[0] == _ANGLE_EAST:
        # east -> up
        # original lever roll code changes east to up_z
        return (_ANGLE_SOUTH, _ANGLE_UP) + angle[2:]
    if angle[0] == _ANGLE_WEST:
        # west -> down
        # original lever roll code changes west to down_x
        return (_ANGLE_WEST, _ANGLE_DOWN) + angle[2:]
    return angle


#def _rotateWithFunc(properties, rotateFunc, angle, angleIndex):
#    if angle is None or angleIndex is None:
#        return
#    propsUpdate = _getPropsFromAngle(rotateFunc(angle))
#    if propsUpdate is not None:
#        properties.update(propsUpdate)


def _rotateLeftBools(properties):
    north = properties.get("north")
    if north is None:
        return False
    west = properties.get("west")
    if west is None:
        return False
    south = properties.get("south")
    if south is None:
        return False
    east = properties.get("east")
    if east is None:
        return False
    properties["west"] = north
    properties["south"] = west
    properties["east"] = south
    properties["north"] = east
    return True


def _flipBools(properties, name1, name2):
    value1 = properties.get(name1)
    if value1 is None:
        return False
    value2 = properties.get(name2)
    if value2 is None:
        return False
    properties[value1] = value2
    properties[value2] = value1
    return True


def _rollBools(properties):
    west = properties.get("west")
    if west is None:
        return False
    east = properties.get("east")
    if east is None:
        return False
    up = properties.get("up")
    if up is None:
        return False
    down = properties.get("down")
    if down is None:
        return False
    properties["down"] = west
    properties["up"] = east
    properties["west"] = up
    properties["east"] = down
    return True


def _flipDoorHinge(properties):
    half = properties.get("half")
    if half != "upper":
        return False
    hinge = properties.get("hinge")
    if hinge is None:
        return False
    if hinge == "left":
        properties["hinge"] = "right"
    elif hinge == "right":
        properties["hinge"] = "left"
    return True


def _rotateLeftProps(properties, angle, angleIndex):
    properties = dict(properties)
    if angle is not None:
        propsUpdate = _getPropsFromAngle(_rotateLeftAngle(angle), angleIndex)
        if propsUpdate is not None:
            properties.update(propsUpdate)
            return properties
#    _rotateWithFunc(properties, _rotateLeftAngle, allProps=allProps)
    _rotateLeftBools(properties)
    return properties


def _flipEastWestProps(properties, angle, angleIndex):
    properties = dict(properties)
    if _flipDoorHinge(properties):
        return properties
    if angle is not None:
        propsUpdate = _getPropsFromAngle(_flipEastWestAngle(angle), angleIndex)
        if propsUpdate is not None:
            properties.update(propsUpdate)
            return properties
#    _rotateWithFunc(properties, _flipEastWestAngle)
    _flipBools(properties, "east", "west")
    return properties


def _flipNorthSouthProps(properties, angle, angleIndex):
    properties = dict(properties)
    if _flipDoorHinge(properties):
        return properties
    if angle is not None:
        propsUpdate = _getPropsFromAngle(_flipNorthSouthAngle(angle), angleIndex)
        if propsUpdate is not None:
            properties.update(propsUpdate)
            return properties
#    _rotateWithFunc(properties, _flipNorthSouthAngle)
    _flipBools(properties, "north", "south")
    return properties


def _flipVerticalProps(properties, angle, angleIndex):
    properties = dict(properties)
    if angle is not None:
        propsUpdate = _getPropsFromAngle(_flipVerticalAngle(angle), angleIndex)
        if propsUpdate is not None:
            properties.update(propsUpdate)
            return properties
#    _rotateWithFunc(properties, _flipVerticalAngle, allProps=allProps)
    _flipBools(properties, "up", "down")
    return properties


def _rollProps(properties, angle, angleIndex):
    properties = dict(properties)
    if angle is not None:
        propsUpdate = _getPropsFromAngle(_rollAngle(angle, angleIndex), angleIndex)
        if propsUpdate is not None:
            properties.update(propsUpdate)
            return properties
#    _rotateWithFunc(properties, _rollAngle, allProps=allProps)
    _rollBools(properties)
    return properties


class _BlockRotation(object):
    def __init__(self, materials):
        blockstateToID = materials.blockstate_api.blockstateToID

        def updateTable(table, block, properties):
            rotatedID, rotatedData = blockstateToID(block.stringID, properties)
            if rotatedID != -1 and rotatedData != -1:
                table[block.ID, block.blockData] = rotatedData

        dataRange = arange(data_limit, dtype="uint8")

        self.rotateLeft = rotateLeft = zeros((id_limit, data_limit), "uint8")
        rotateLeft[:] = dataRange
        self.flipEastWest = flipEastWest = zeros((id_limit, data_limit), "uint8")
        flipEastWest[:] = dataRange
        self.flipNorthSouth = flipNorthSouth = zeros((id_limit, data_limit), "uint8")
        flipNorthSouth[:] = dataRange
        self.flipVertical = flipVertical = zeros((id_limit, data_limit), "uint8")
        flipVertical[:] = dataRange
        self.roll = roll = zeros((id_limit, data_limit), "uint8")
        roll[:] = dataRange

        for block in materials:
            properties = block.properties
            if not bool(properties):
                continue
            blockID = block.ID
            blockData = block.blockData
            stringID = block.stringID
            allProps = materials.properties[blockID]

            angleFull = _getAngleFromProps(properties, allProps)
            if angleFull is not None:
                angle, angleIndex = angleFull
            else:
                angle = angleIndex = None

            updateTable(rotateLeft, block, _rotateLeftProps(properties, angle, angleIndex))
            updateTable(flipEastWest, block, _flipEastWestProps(properties, angle, angleIndex))
            updateTable(flipNorthSouth, block, _flipNorthSouthProps(properties, angle, angleIndex))
            updateTable(flipVertical, block, _flipVerticalProps(properties, angle, angleIndex))
            updateTable(roll, block, _rollProps(properties, angle, angleIndex))


def FlipVertical(blocks, data, mats=alphaMaterials):
    if hasattr(mats, "blockRotation"):
        blockRotation = mats.blockRotation
    else:
        blockRotation = mats.blockRotation = _BlockRotation(mats)
    # pcm1k TODO - ignore blocks that are above the limit for now
#    data[:] = blockRotation.flipVertical[blocks, data]
    belowLimit = (blocks < id_limit) & (data < data_limit)
    data[belowLimit] = blockRotation.flipVertical[blocks[belowLimit], data[belowLimit]]


def FlipNorthSouth(blocks, data, mats=alphaMaterials):
    if hasattr(mats, "blockRotation"):
        blockRotation = mats.blockRotation
    else:
        blockRotation = mats.blockRotation = _BlockRotation(mats)
    # This is NOT a mistake. The original code has north/south and east/west swapped
    # pcm1k TODO - ignore blocks that are above the limit for now
#    data[:] = blockRotation.flipEastWest[blocks, data]
    belowLimit = (blocks < id_limit) & (data < data_limit)
    data[belowLimit] = blockRotation.flipEastWest[blocks[belowLimit], data[belowLimit]]


def FlipEastWest(blocks, data, mats=alphaMaterials):
    if hasattr(mats, "blockRotation"):
        blockRotation = mats.blockRotation
    else:
        blockRotation = mats.blockRotation = _BlockRotation(mats)
    # This is NOT a mistake. The original code has north/south and east/west swapped
    # pcm1k TODO - ignore blocks that are above the limit for now
#    data[:] = blockRotation.flipNorthSouth[blocks, data]
    belowLimit = (blocks < id_limit) & (data < data_limit)
    data[belowLimit] = blockRotation.flipNorthSouth[blocks[belowLimit], data[belowLimit]]


def RotateLeft(blocks, data, mats=alphaMaterials):
    if hasattr(mats, "blockRotation"):
        blockRotation = mats.blockRotation
    else:
        blockRotation = mats.blockRotation = _BlockRotation(mats)
    # pcm1k TODO - ignore blocks that are above the limit for now
#    data[:] = blockRotation.rotateLeft[blocks, data]
    belowLimit = (blocks < id_limit) & (data < data_limit)
    data[belowLimit] = blockRotation.rotateLeft[blocks[belowLimit], data[belowLimit]]


def Roll(blocks, data, mats=alphaMaterials):
    if hasattr(mats, "blockRotation"):
        blockRotation = mats.blockRotation
    else:
        blockRotation = mats.blockRotation = _BlockRotation(mats)
    # pcm1k TODO - ignore blocks that are above the limit for now
#    data[:] = blockRotation.roll[blocks, data]
    belowLimit = (blocks < id_limit) & (data < data_limit)
    data[belowLimit] = blockRotation.roll[blocks[belowLimit], data[belowLimit]]
