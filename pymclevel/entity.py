'''
Created on Jul 23, 2011
@author: Rio
'''
from logging import getLogger
from math import isnan

import random
import nbt
from copy import deepcopy
from id_definitions import BaseDefs, MCEditDefsIds

__all__ = ["Entity", "TileEntity", "TileTick"]

#UNKNOWN_ENTITY_MASK = 1000

logger = getLogger(__name__)


class TileEntityDefs(BaseDefs):
    _oldToDefIds = {
        "Airportal": "DEF_TILEENTITIES_END_PORTAL",
        "Banner": "DEF_TILEENTITIES_BANNER",
        "Beacon": "DEF_TILEENTITIES_BEACON",
        "Cauldron": "DEF_TILEENTITIES_BREWING_STAND",
        "Chest": "DEF_TILEENTITIES_CHEST",
        "Comparator": "DEF_TILEENTITIES_COMPARATOR",
        "Control": "DEF_TILEENTITIES_COMMAND_BLOCK",
        "DLDetector": "DEF_TILEENTITIES_DAYLIGHT_DETECTOR",
        "Dropper": "DEF_TILEENTITIES_DROPPER",
        "EnchantTable": "DEF_TILEENTITIES_ENCHANTING_TABLE",
        "EnderChest": "DEF_TILEENTITIES_ENDER_CHEST",
        "EndGateway": "DEF_TILEENTITIES_END_GATEWAY",
        "FlowerPot": "DEF_TILEENTITIES_FLOWER_POT",
        "Furnace": "DEF_TILEENTITIES_FURNACE",
        "Hopper": "DEF_TILEENTITIES_HOPPER",
        "MobSpawner": "DEF_TILEENTITIES_MOB_SPAWNER",
        "Music": "DEF_TILEENTITIES_NOTEBLOCK",
        "Piston": "DEF_TILEENTITIES_PISTON",
        "RecordPlayer": "DEF_TILEENTITIES_JUKEBOX",
        "Sign": "DEF_TILEENTITIES_SIGN",
        "Skull": "DEF_TILEENTITIES_SKULL",
        "Structure": "DEF_TILEENTITIES_STRUCTURE_BLOCK",
        "Trap": "DEF_TILEENTITIES_DISPENSER",
    }

    _defToOldIds = {newId: oldId for oldId, newId in _oldToDefIds.iteritems()}

    _defsCache = {}

    def __init__(self, defsIds):
        super(TileEntityDefs, self).__init__(defsIds)

        self.baseStructures = {}
        self.stringNames = {}
        self.knownIDs = []
        self.maxItems = {}
        self.slotNames = {}

        if defsIds is None:
            return

        def parseNbtDict(jsonTag):
            if not isinstance(jsonTag, dict):
                return None

            tagType = getattr(nbt, "TAG_%s" % jsonTag["type"])
            value = jsonTag.get("value")
            if value is None:
                return tagType()

            if tagType is nbt.TAG_Compound:
                resultTag = tagType()
                for name, jsonTag2 in value.iteritems():
                    resultTag[name] = parseNbtDict(jsonTag2)
                return resultTag
            if tagType is nbt.TAG_List:
                resultTag = tagType()
                for jsonTag2 in value:
                    resultTag.append(parseNbtDict(jsonTag2))
                return resultTag

            return tagType(value)

        for idStr, defId in defsIds.mcedit_ids["tileentities"].iteritems():
            if not isinstance(idStr, basestring):
                continue
            item = defsIds.mcedit_defs[defId]

            self.knownIDs.append(idStr)

            maxItems = item.get("maxItems")
            if maxItems is not None and isinstance(maxItems, int):
                self.maxItems[idStr] = maxItems

            slotNames = item.get("slotNames")
            if slotNames is not None and isinstance(slotNames, dict):
                self.slotNames[idStr] = {int(slot): slotName for slot, slotName in slotNames.iteritems()}

            baseStructure = item.get("baseStructure")
            if baseStructure is not None and isinstance(baseStructure, dict):
                self.baseStructures[idStr] = parseNbtDict({"type": "Compound", "value": baseStructure})
        for idStr, defId in defsIds.mcedit_ids["blocks"].iteritems():
            if not isinstance(idStr, basestring):
                continue
            item = defsIds.mcedit_defs[defId]

            tileentity = item.get("tileentity")
            if tileentity is not None and isinstance(tileentity, basestring):
                defIdTe = MCEditDefsIds.formatDefId("tileentities", tileentity)
                idStrTe = self.getStrId(defIdTe)
                if idStrTe is None:
                    logger.warn("Could not find tileentity %s", defIdTe)
                    continue
                self.stringNames[idStr] = idStrTe

    @classmethod
    def getDefs(cls, defsIds, forceNew=False):
        entityDefs = cls._getBaseDefs(defsIds, cls._defsCache, forceNew=forceNew, globalDefs=TileEntity.globalDefs)
        TileEntity.updateGlobal(entityDefs)
        return entityDefs

    def Create(self, tileEntityID, pos=(0, 0, 0), convertOld=True, **kw):
        def handleSpecialStruct(defId, name, **kw):
            if defId == "DEF_TILEENTITIES_MOB_SPAWNER":
                if self.defsIds is None:
                    return None

                entity = kw.get("entity")
                if name == "EntityId":
                    entityDefs = getEntityDefs(self.defsIds)
                    structTag = nbt.TAG_String(entityDefs.getStrId("DEF_ENTITIES_PIG"))
                    return structTag
                if name == "SpawnData":
                    entityDefs = getEntityDefs(self.defsIds)
                    spawn_id = nbt.TAG_String(entityDefs.getStrId("DEF_ENTITIES_PIG"), "id")
                    structTag = nbt.TAG_Compound()
                    if bool(entity):
                        for k, v in entity.iteritems():
                            structTag[k] = deepcopy(v)
                    else:
                        structTag.add(spawn_id)
                    return structTag
            return None

        def getNewId(oldId):
            if oldId not in self._oldToDefIds or self.defsIds is None:
                return oldId
            item = self.defsIds.get_def(self._oldToDefIds[oldId])
            if item is None:
                return oldId
            return item.get("idStr", oldId)

        tileEntityTag = self.baseStructures.get(tileEntityID)
        if tileEntityTag is None:
            tileEntityTag = nbt.TAG_Compound()
        else:
            tileEntityTag = deepcopy(tileEntityTag)

        if convertOld:
            tileEntityID = getNewId(tileEntityID)
        tileEntityTag["id"] = nbt.TAG_String(tileEntityID)

        defId = self.getDefId(tileEntityID)
        for name in tileEntityTag.iterkeys():
            structTag = handleSpecialStruct(defId, name, **kw)
            if structTag is not None:
                tileEntityTag[name] = structTag

        TileEntity.setpos(tileEntityTag, pos)
        return tileEntityTag

    def _adjustCommandTile(self, eTag, copyOffset, toSchematic, movePos):
        def num(x):
            try:
                return int(x)
            except ValueError:
                return float(x)

        # pcm1k TODO - backwards compatibility with the old system
        def coordAny(c, movePos, offset):
            return str(num(c) + offset)

        def coordX(x, movePos):
            return coordAny(x, movePos, copyOffset[0])

        def coordY(y, movePos):
            return coordAny(y, movePos, copyOffset[1])

        def coordZ(z, movePos):
            return coordAny(z, movePos, copyOffset[2])

        def coords(x, y, z, movePos):
            if x[0] != "~":
                x = coordX(x, movePos)
            if y[0] != "~":
                y = coordY(y, movePos)
            if z[0] != "~":
                z = coordZ(z, movePos)
            return x, y, z

        def adjustSelector(selector, moveCommandPos):
            # @a[<args>]
            if len(selector) <= 4 or selector[0] != "@" or selector[2] != "[" or selector[-1] != "]":
                return selector

            if "0" <= selector[3] <= "9":
                selSplit = selector[3:-1].split(",", 3)
                if len(selSplit) < 3:
                    return selector
                selSplit[0] = coordX(selSplit[0], moveCommandPos)
                selSplit[1] = coordY(selSplit[1], moveCommandPos)
                selSplit[2] = coordZ(selSplit[2], moveCommandPos)
            else:
                selSplit = selector[3:-1].split(",")
                for argI, arg in enumerate(selSplit):
                    if arg.startswith("x="):
                        selSplit[argI] = arg[:2] + coordX(arg[2:], moveCommandPos)
                    elif arg.startswith("y="):
                        selSplit[argI] = arg[:2] + coordY(arg[2:], moveCommandPos)
                    elif arg.startswith("z="):
                        selSplit[argI] = arg[:2] + coordZ(arg[2:], moveCommandPos)
            selector = selector[:3] + ",".join(selSplit) + selector[-1]
            return selector

        def adjustCommandWords(words, moveCommandPos):
            if not bool(words):
                return
            firstWord = words[0]
            if firstWord.startswith("/"):
                firstWord = firstWord[1:]

            if len(words) >= 5 and (
                # tp <target player> <x> <y> <z> <yaw> <pitch>
                firstWord == "tp" or
                # particle <name> <x> <y> <z>
                firstWord == "particle" or
                # replaceitem block <x> <y> <z>
                firstWord == "replaceitem" and words[1] == "block" or
                # spawnpoint <targets> <x> <y> <z> <angle>
                firstWord == "spawnpoint" or
                # stats block <x> <y> <z>
                firstWord == "stats" and words[1] == "block" or
                # summon <entity> <x> <y> <z> <nbt>
                firstWord == "summon"):
                x, y, z = words[2:5]
                words[2:5] = coords(x, y, z, moveCommandPos)
            elif len(words) >= 4 and (
                # blockdata <x> <y> <z> <dataTag>
                firstWord == "blockdata" or
                # setblock <x> <y> <z> <block>
                firstWord == "setblock" or
                # setworldspawn <x> <y> <z> <angle>
                firstWord == "setworldspawn"):
                x, y, z = words[1:4]
                words[1:4] = coords(x, y, z, moveCommandPos)
            # pcm1k TODO - add the rest of these command comments
            elif len(words) >= 6 and firstWord == "playsound":
                x, y, z = words[3:6]
                words[3:6] = coords(x, y, z, moveCommandPos)
            elif len(words) >= 10 and firstWord == "clone":
                x1, y1, z1, x2, y2, z2, x, y, z = words[1:10]
                x1, y1, z1 = coords(x1, y1, z1, moveCommandPos)
                x2, y2, z2 = coords(x2, y2, z2, moveCommandPos)
                x, y, z = coords(x, y, z, moveCommandPos)

                words[1:10] = x1, y1, z1, x2, y2, z2, x, y, z
            elif len(words) >= 7 and firstWord == "fill":
                x1, y1, z1, x2, y2, z2 = words[1:7]
                x1, y1, z1 = coords(x1, y1, z1, moveCommandPos)
                x2, y2, z2 = coords(x2, y2, z2, moveCommandPos)

                words[1:7] = x1, y1, z1, x2, y2, z2
            elif len(words) >= 3 and firstWord == "spreadplayers":
                x, z = words[1:3]
                if x[0] != "~":
                    x = coordX(x, moveCommandPos)
                if z[0] != "~":
                    z = coordZ(z, moveCommandPos)

                words[1:3] = x, z
            elif len(words) >= 4 and firstWord == "worldborder" and words[1] == "center":
                x, z = words[2:4]
                if x[0] != "~":
                    x = coordX(x, moveCommandPos)
                if z[0] != "~":
                    z = coordZ(z, moveCommandPos)

                words[2:4] = x, z

        def adjustExecute(words, moveCommandPos):
            # execute <entity> <x> <y> <z> <command>
            while len(words) >= 5:
                firstWord = words[0]
                if firstWord.startswith("/"):
                    firstWord = firstWord[1:]
                if firstWord != "execute":
                    break

                x, y, z = words[2:5]
                words[2:5] = coords(x, y, z, moveCommandPos)

                # execute <entity> <x> <y> <z> detect <x2> <y2> <z2>
                if len(words) >= 9 and words[5] == "detect":
                    x2, y2, z2 = words[6:9]
                    words[6:9] = coords(x2, y2, z2, moveCommandPos)
                    words = words[9:]
                else:
                    words = words[5:]
            return words

        def adjustCommand(command, moveCommandPos):
            if not bool(command):
                return None

            words = command.split(" ")

            for i, word in enumerate(words):
                words[i] = adjustSelector(word, moveCommandPos)

            shiftedWords = adjustExecute(words, moveCommandPos)

            adjustCommandWords(shiftedWords, moveCommandPos)
            words[-len(shiftedWords):] = shiftedWords
            command = " ".join(words)
            return command

        if toSchematic is None:
            offsetCommand = eTag.pop("MCEditOffsetCommand", None)
            if not movePos:
                # only remove the prefixed tag
                return
            if offsetCommand is None:
                # offset the normal position if the prefixed tag is unavailable
                offsetCommand = eTag["Command"]
            command = adjustCommand(offsetCommand.value, movePos)
            if command is not None:
                # save it in the normal tag
                eTag["Command"].value = command
            return

        if toSchematic:
            # offset the normal position
            command = adjustCommand(eTag["Command"].value, movePos)
            if command is not None:
                # save it in the prefixed tag
                eTag["MCEditOffsetCommand"] = nbt.TAG_String(command)
            return

        offsetCommand = eTag.pop("MCEditOffsetCommand", None)
        if not movePos or offsetCommand is None:
            # only remove the prefixed tag
            return
        command = adjustCommand(offsetCommand.value, movePos)
        if command is not None:
            # save it in the normal tag
            eTag["Command"].value = command

    def _adjustSpawnerTile(self, eTag, copyOffset, toSchematic, movePos):
        def adjustMobs(mobs, copyOffset, toSchematic, movePos):
            for mob in mobs:
                # Why do we get a unicode object as tag 'mob'?
                if isinstance(mob, basestring) or "Pos" not in mob:
                    continue

                if toSchematic is None:
                    offsetPos = mob.pop("MCEditOffsetPos", None)
                    if not movePos:
                        # only remove the prefixed tag
                        continue
                    if offsetPos is None:
                        # offset the normal position if the prefixed tag is unavailable
                        offsetPos = Entity.pos(mob)
                    else:
                        offsetPos = [p.value for p in offsetPos]
                    pos = [c + o for c, o in zip(offsetPos, copyOffset)]
                    # save it in the normal tag
                    Entity.setpos(mob, pos)
                    continue

                if toSchematic:
                    # offset the normal position
                    pos = Entity.pos(mob)
                    pos = [c + o for c, o in zip(pos, copyOffset)]
                    # save it in the prefixed tag
                    mob["MCEditOffsetPos"] = nbt.TAG_List([nbt.TAG_Double(p) for p in pos])
                    continue

                offsetPos = mob.pop("MCEditOffsetPos", None)
                if not movePos or offsetPos is None:
                    # only remove the prefixed tag
                    continue
                offsetPos = [p.value for p in offsetPos]
                pos = [c + o for c, o in zip(offsetPos, copyOffset)]
                # save it in the normal tag
                Entity.setpos(mob, pos)

        def collectMobs(eTag):
            mobs = []
            mob = eTag.get("SpawnData")
            if bool(mob):
                mobs.append(mob)
            potentials = eTag.get("SpawnPotentials", ())
            for p in potentials:
                properties = p.get("Properties")
                if bool(properties):
                    mobs.extend(properties)
                    continue
                entity = p.get("Entity")
                if bool(entity):
                    mobs.extend(entity)
            return mobs

        mobs = collectMobs(eTag)
        adjustMobs(mobs, copyOffset, toSchematic, movePos)

    def copyWithOffset(self, tileEntity, copyOffset, toSchematic=None, moveCommandPos=False, moveSpawnerPos=False):
        # if toSchematic = None:
        #     if movePos:
        #         offset and remove the prefixed tag if it exists and save it in the normal tag, otherwise offset the normal position
        #     else:
        #         remove the prefixed tag if it exists, otherwise do nothing
        # if toSchematic = True:
        #     if movePos:
        #         offset the normal position and save it in a tag prefixed with "MCEditOffset"
        #     else:
        #         offset the normal position and save it in a tag prefixed with "MCEditOffset"
        # if toSchematic = False:
        #     if movePos:
        #         offset and remove the prefixed tag if it exists and save it in the normal tag, otherwise do nothing
        #     else:
        #         remove the prefixed tag if it exists, otherwise do nothing

        eTag = deepcopy(tileEntity)
        eTag["x"] = nbt.TAG_Int(tileEntity["x"].value + copyOffset[0])
        eTag["y"] = nbt.TAG_Int(tileEntity["y"].value + copyOffset[1])
        eTag["z"] = nbt.TAG_Int(tileEntity["z"].value + copyOffset[2])

        defId = self.getDefId(eTag["id"].value)
        if defId == "DEF_TILEENTITIES_MOB_SPAWNER":
            self._adjustSpawnerTile(eTag, copyOffset, toSchematic, moveSpawnerPos)
        elif defId == "DEF_TILEENTITIES_COMMAND_BLOCK":
            self._adjustCommandTile(eTag, copyOffset, toSchematic, moveCommandPos)

        return eTag

    @staticmethod
    def _getDefId(defsIds, oldToDefIds, prefix, entityId, default, fallbackOld):
        if defsIds is None:
            if fallbackOld:
                # fallback to oldIds
                return oldToDefIds.get(entityId, default)
            return default

        return defsIds.get_id(prefix, entityId, default)

    @staticmethod
    def _getStrId(defsIds, defToOldIds, prefix, entityId, default, fallbackOld):
        if defsIds is None:
            if fallbackOld:
                # fallback to oldIds
                return defToOldIds.get(entityId, default)
            return default

        item = defsIds.get_id(prefix, entityId, resolve=True)
        if item is not None and "idStr" in item:
            if "namespace" in item and item["namespace"]:
                return "%s:%s" % (item["namespace"], item["idStr"])
            return item["idStr"]

        if fallbackOld:
            # fallback to oldIds
            return defToOldIds.get(entityId, default)
        return default

    @staticmethod
    def _getName(defsIds, prefix, entityId, default):
        if defsIds is None:
            return default

        item = defsIds.get_id(prefix, entityId, resolve=True)
        if item is not None:
            return item.get("name", default)
        return default

    def getDefId(self, entityId, default=None, fallbackOld=True):
        return self._getDefId(self.defsIds, self._oldToDefIds, "tileentities", entityId, default, fallbackOld)

    def getStrId(self, entityId, default=None, fallbackOld=True):
        return self._getStrId(self.defsIds, self._defToOldIds, "tileentities", entityId, default, fallbackOld)

    def getName(self, entityId, default=None):
        return self._getName(self.defsIds, "tileentities", entityId, default)


class EntityDefs(BaseDefs):
    _oldToDefIds = {
        "AreaEffectCloud": "DEF_ENTITIES_AREA_EFFECT_CLOUD",
        "ArmorStand": "DEF_ENTITIES_ARMOR_STAND",
        "Arrow": "DEF_ENTITIES_ARROW",
        "Bat": "DEF_ENTITIES_BAT",
        "Blaze": "DEF_ENTITIES_BLAZE",
        "Boat": "DEF_ENTITIES_BOAT",
        "CaveSpider": "DEF_ENTITIES_CAVE_SPIDER",
        "Chicken": "DEF_ENTITIES_CHICKEN",
        "Cow": "DEF_ENTITIES_COW",
        "Creeper": "DEF_ENTITIES_CREEPER",
        "DragonFireball": "DEF_ENTITIES_DRAGON_FIREBALL",
        "EnderCrystal": "DEF_ENTITIES_ENDER_CRYSTAL",
        "EnderDragon": "DEF_ENTITIES_ENDER_DRAGON",
        "Enderman": "DEF_ENTITIES_ENDERMAN",
        "Endermite": "DEF_ENTITIES_ENDERMITE",
        "EntityHorse": "DEF_ENTITIES_HORSE",
        "EyeOfEnderSignal": "DEF_ENTITIES_EYE_OF_ENDER_SIGNAL",
        "FallingSand": "DEF_ENTITIES_FALLING_BLOCK",
        "Fireball": "DEF_ENTITIES_FIREBALL",
        "FireworksRocketEntity": "DEF_ENTITIES_FIREWORKS_ROCKET",
        "Ghast": "DEF_ENTITIES_GHAST",
        "Giant": "DEF_ENTITIES_GIANT",
        "Guardian": "DEF_ENTITIES_GUARDIAN",
        "ItemFrame": "DEF_ENTITIES_ITEM_FRAME",
        "Item": "DEF_ENTITIES_ITEM",
        "LavaSlime": "DEF_ENTITIES_MAGMA_CUBE",
        "LeashKnot": "DEF_ENTITIES_LEASH_KNOT",
        "MinecartChest": "DEF_ENTITIES_CHEST_MINECART",
        "MinecartCommandBlock": "DEF_ENTITIES_COMMANDBLOCK_MINECART",
        "MinecartFurnace": "DEF_ENTITIES_FURNACE_MINECART",
        "MinecartHopper": "DEF_ENTITIES_HOPPER_MINECART",
        "MinecartRideable": "DEF_ENTITIES_MINECART",
        "MinecartSpawner": "DEF_ENTITIES_SPAWNER_MINECART",
        "MinecartTNT": "DEF_ENTITIES_TNT_MINECART",
        "Mob": "DEF_ENTITIES_EMPTY",
        "Monster": "DEF_ENTITIES_HUMAN",
        "MushroomCow": "DEF_ENTITIES_MOOSHROOM",
        "Ozelot": "DEF_ENTITIES_OCELOT",
        "Painting": "DEF_ENTITIES_PAINTING",
        "Pig": "DEF_ENTITIES_PIG",
        "PigZombie": "DEF_ENTITIES_ZOMBIE_PIGMAN",
        "PolarBear": "DEF_ENTITIES_POLAR_BEAR",
        "PrimedTnt": "DEF_ENTITIES_TNT",
        "Rabbit": "DEF_ENTITIES_RABBIT",
        "Sheep": "DEF_ENTITIES_SHEEP",
        "ShulkerBullet": "DEF_ENTITIES_SHULKER_BULLET",
        "Shulker": "DEF_ENTITIES_SHULKER",
        "Silverfish": "DEF_ENTITIES_SILVERFISH",
        "Skeleton": "DEF_ENTITIES_SKELETON",
        "Slime": "DEF_ENTITIES_SLIME",
        "SmallFireball": "DEF_ENTITIES_SMALL_FIREBALL",
        "Snowball": "DEF_ENTITIES_SNOWBALL",
        "SnowMan": "DEF_ENTITIES_SNOWMAN",
        "SpectralArrow": "DEF_ENTITIES_SPECTRAL_ARROW",
        "Spider": "DEF_ENTITIES_SPIDER",
        "Squid": "DEF_ENTITIES_SQUID",
        "ThrownEgg": "DEF_ENTITIES_EGG",
        "ThrownEnderpearl": "DEF_ENTITIES_ENDER_PEARL",
        "ThrownExpBottle": "DEF_ENTITIES_XP_BOTTLE",
        "ThrownPotion": "DEF_ENTITIES_POTION",
        "VillagerGolem": "DEF_ENTITIES_VILLAGER_GOLEM",
        "Villager": "DEF_ENTITIES_VILLAGER",
        "Witch": "DEF_ENTITIES_WITCH",
        "WitherBoss": "DEF_ENTITIES_WITHER",
        "WitherSkull": "DEF_ENTITIES_WITHER_SKULL",
        "Wolf": "DEF_ENTITIES_WOLF",
        "XPOrb": "DEF_ENTITIES_XP_ORB",
        "Zombie": "DEF_ENTITIES_ZOMBIE",
    }

    _defToOldIds = {newId: oldId for oldId, newId in _oldToDefIds.iteritems()}

    _defsCache = {}

    def __init__(self, defsIds):
        super(EntityDefs, self).__init__(defsIds)

        self.entityList = {}
        self.monsters = []
        self.maxItems = {}

        if defsIds is None:
            return

        for idStr, defId in defsIds.mcedit_ids["entities"].iteritems():
            if not isinstance(idStr, basestring):
                continue
            item = defsIds.mcedit_defs[defId]

            self.entityList[idStr] = item["id"]
            maxItems = item.get("maxItems")
            if maxItems is not None and isinstance(maxItems, int):
                self.maxItems[idStr] = maxItems

        spawnerMonsters = defsIds.get_def("spawner_monsters")
        if spawnerMonsters is not None:
            for mob in spawnerMonsters:
                defId = MCEditDefsIds.formatDefId("entities", mob)
                idStr = self.getStrId(defId)
                if idStr is None:
                    logger.warn("Could not find spawner entity %s", defId)
                    continue
                self.monsters.append(idStr)
        else:
            self.monsters.extend(self.entityList.iterkeys())

    @classmethod
    def getDefs(cls, defsIds, forceNew=False):
        entityDefs = cls._getBaseDefs(defsIds, cls._defsCache, forceNew=forceNew, globalDefs=Entity.globalDefs)
        Entity.updateGlobal(entityDefs)
        return entityDefs

    def Create(self, entityID, pos=(0, 0, 0), convertOld=True, **kw):
        def getNewId(oldId):
            if oldId not in self._oldToDefIds or self.defsIds is None:
                return oldId
            item = self.defsIds.get_def(self._oldToDefIds[oldId])
            if item is None:
                return oldId
            return item.get("idStr", oldId)

        entityTag = nbt.TAG_Compound()
        if convertOld:
            entityID = getNewId(entityID)
        entityTag["id"] = nbt.TAG_String(entityID)
        Entity.setpos(entityTag, pos)
        return entityTag

    def copyWithOffset(self, entity, copyOffset, regenerateUUID=False):
        eTag = deepcopy(entity)

        # Need to check the content of the copy to regenerate the possible sub entities UUIDs.
        # A simple fix for the 1.9+ minecarts is proposed.

        positionTags = map(lambda p, co: type(p)((p.value + co)), eTag["Pos"], copyOffset)
        eTag["Pos"] = nbt.TAG_List(positionTags)

        # Trying more agnostic way
        if "TileX" in eTag and "TileY" in eTag and "TileZ" in eTag:
            eTag["TileX"].value += copyOffset[0]
            eTag["TileY"].value += copyOffset[1]
            eTag["TileZ"].value += copyOffset[2]

        if "Riding" in eTag:
            eTag["Riding"] = self.copyWithOffset(eTag["Riding"], copyOffset)

        # # Fix for 1.9+ minecarts
        if "Passengers" in eTag:
            passengers = nbt.TAG_List()
            for passenger in eTag["Passengers"]:
                passengers.append(self.copyWithOffset(passenger, copyOffset, regenerateUUID))
            eTag["Passengers"] = passengers
        # #

        if regenerateUUID:
            # Courtesy of SethBling
            eTag["UUIDMost"] = nbt.TAG_Long((random.getrandbits(47) << 16) | (1 << 12) | random.getrandbits(12))
            eTag["UUIDLeast"] = nbt.TAG_Long(-((7 << 60) | random.getrandbits(60)))
        return eTag

    def getDefId(self, entityId, default=None, fallbackOld=True):
        return TileEntityDefs._getDefId(self.defsIds, self._oldToDefIds, "entities", entityId, default, fallbackOld)

    def getId(self, v, default="No ID"):
        if self.defsIds is None:
            return default
        item = self.defsIds.get_id("entities", v, resolve=True)
        if item is None:
            return default
        return item.get("id", default)

    def getStrId(self, entityId, default=None, fallbackOld=True):
        return TileEntityDefs._getStrId(self.defsIds, self._defToOldIds, "entities", entityId, default, fallbackOld)

    def getName(self, entityId, default=None):
        return TileEntityDefs._getName(self.defsIds, "entities", entityId, default)


#class PocketEntityDefs(EntityDefs):
#    unknown_entity_top = UNKNOWN_ENTITY_MASK + 0
#    entityList = {}

#    def getNumId(self, v):
#        """Returns the numeric ID of an entity, or a generated one if the entity is not known.
#        The generated one is generated like this: 'UNKNOWN_ENTITY_MASK + X', where 'X' is a number.
#        The first unknown entity will have the numerical ID 1001, the second one 1002, and so on.
#        :v: the entity string ID to search for."""
#        id_ = self.getId(v)
#        if not isinstance(id_, int) and v not in self.entityList:
#            id_ = self.unknown_entity_top + 1
#            self.entityList[v] = self.entityList["Entity %s" % id_] = id_
#            self.unknown_entity_top += 1
#        return id_


# pcm1k TODO - This class should be used to store data about the entity definition. It will also provide an abstraction around certain entity properties, with subclasses for different applicable entity types
class TileEntity(object):
    # trying to keep backwards compatibility
    globalDefs = TileEntityDefs(None)

    stringNames = {}
    knownIDs = []
    maxItems = {}
    slotNames = {}

    @classmethod
    def updateGlobal(cls, entityDefs):
        cls.globalDefs = entityDefs
        cls.stringNames = entityDefs.stringNames
        cls.knownIDs = entityDefs.knownIDs
        cls.maxItems = entityDefs.maxItems
        cls.slotNames = entityDefs.slotNames

    @classmethod
    def Create(cls, tileEntityID, pos=(0, 0, 0), defsIds=None, **kw):
        if defsIds is not None and defsIds is not cls.globalDefs.defsIds:
            # redirect to the correct TileEntityDefs object
            cls.updateGlobal(getTileEntityDefs(defsIds))
        return cls.globalDefs.Create(tileEntityID, pos=pos, convertOld=True, **kw)

    @classmethod
    def copyWithOffset(cls, tileEntity, copyOffset, staticCommands, moveSpawnerPos, first, cancelCommandBlockOffset=False, defsIds=None):
        if defsIds is not None and defsIds is not cls.globalDefs.defsIds:
            # redirect to the correct TileEntityDefs object
            cls.updateGlobal(getTileEntityDefs(defsIds))
        if cancelCommandBlockOffset:
            first = None
            staticCommands = False
            moveSpawnerPos = False
        return cls.globalDefs.copyWithOffset(tileEntity, copyOffset, toSchematic=first, moveCommandPos=staticCommands, moveSpawnerPos=moveSpawnerPos)

    @classmethod
    def pos(cls, tag):
        return [tag[a].value for a in 'xyz']

    @classmethod
    def setpos(cls, tag, pos):
        for a, p in zip('xyz', pos):
            tag[a] = nbt.TAG_Int(p)


class Entity(object):
    # trying to keep backwards compatibility
    globalDefs = EntityDefs(None)

    entityList = {}
    monsters = []
    maxItems = {}

    @classmethod
    def updateGlobal(cls, entityDefs):
        cls.globalDefs = entityDefs
        cls.entityList = entityDefs.entityList
        cls.monsters = entityDefs.monsters
        cls.maxItems = entityDefs.maxItems

    @classmethod
    def Create(cls, entityID, pos=(0, 0, 0), **kw):
        return cls.globalDefs.Create(entityID, pos=pos, convertOld=True, **kw)

    @classmethod
    def copyWithOffset(cls, entity, copyOffset, regenerateUUID=False):
        return cls.globalDefs.copyWithOffset(entity, copyOffset, regenerateUUID=regenerateUUID)

    @classmethod
    def getId(cls, v, default="No ID"):
        return cls.globalDefs.getId(v, default=default)

    @classmethod
    def pos(cls, tag):
        if "Pos" not in tag:
            raise InvalidEntity(tag)

        values = [a.value for a in tag["Pos"]]

        if isnan(values[0]) and 'xTile' in tag:
            values[0] = tag['xTile'].value
        if isnan(values[1]) and 'yTile' in tag:
            values[1] = tag['yTile'].value
        if isnan(values[2]) and 'zTile' in tag:
            values[2] = tag['zTile'].value

        return values

    @classmethod
    def setpos(cls, tag, pos):
        tag["Pos"] = nbt.TAG_List([nbt.TAG_Double(p) for p in pos])


getTileEntityDefs = TileEntityDefs.getDefs
getEntityDefs = EntityDefs.getDefs


class TileTick(object):
    @classmethod
    def pos(cls, tag):
        return [tag[a].value for a in 'xyz']


class InvalidEntity(ValueError):
    pass


class InvalidTileEntity(ValueError):
    pass
