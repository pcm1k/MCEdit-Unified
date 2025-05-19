'''
Created on Jul 23, 2011
@author: Rio
'''
from logging import getLogger
from math import isnan

import random
import nbt
from copy import deepcopy
from id_definitions import BaseDefs, MCEditDefsIds, getBaseDefs

__all__ = ["Entity", "TileEntity", "TileTick"]

UNKNOWN_ENTITY_MASK = 1000

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

    def __init__(self, defsIds):
        super(TileEntityDefs, self).__init__(defsIds)

        self.baseStructures = {}
        self.stringNames = {}
        self.knownIDs = []
        self.maxItems = {}
        self.slotNames = {}

        if defsIds is None:
            return

        def parseBaseStruct(jsonStruct):
            result = []
            for name, data in jsonStruct.iteritems():
                tagType = getattr(nbt, "TAG_%s" % data["type"])
                # pcm1k - maybe just create an actual NBT tag object?
                entry = name, tagType, data.get("value")
                result.append(entry)
            return tuple(result)

        for idStr, defId in defsIds.mcedit_ids["tileentities"].iteritems():
            if not isinstance(idStr, basestring):
                continue
            item = defsIds.mcedit_defs[defId]
            self.knownIDs.append(idStr)
            if "maxItems" in item and isinstance(item["maxItems"], int):
                self.maxItems[idStr] = item["maxItems"]
            if "slotNames" in item and isinstance(item["slotNames"], dict):
                self.slotNames[idStr] = {int(slot): slotName for slot, slotName in item["slotNames"].iteritems()}
            if "baseStructure" in item and isinstance(item["baseStructure"], dict):
                # pcm1k - this should be changed to allow nested compound tags
                self.baseStructures[idStr] = parseBaseStruct(item["baseStructure"])
        for idStr, defId in defsIds.mcedit_ids["blocks"].iteritems():
            if not isinstance(idStr, basestring):
                continue
            item = defsIds.mcedit_defs[defId]
            if "tileentity" in item and isinstance(item["tileentity"], basestring):
                defIdTe = MCEditDefsIds.formatDefId("tileentities", item["tileentity"])
                idStrTe = self.getStrId(defIdTe)
                if idStrTe is None:
                    logger.warn("Could not find tileentity %s", defIdTe)
                    continue
                self.stringNames[idStr] = idStrTe

    def Create(self, tileEntityID, pos=(0, 0, 0), convertOld=True, **kw):
        def handleSpecialStruct(tileEntityTag, defId, name, tag, **kw):
            if defId == "DEF_TILEENTITIES_MOB_SPAWNER":
                if self.defsIds is None:
                    return False

                entity = kw.get("entity")
                if name == "EntityId":
                    entityDefs = getEntityDefs(self.defsIds)
                    tileEntityTag[name] = nbt.TAG_String(entityDefs.getStrId("DEF_ENTITIES_PIG"))
                    return True
                if name == "SpawnData":
                    entityDefs = getEntityDefs(self.defsIds)
                    spawn_id = nbt.TAG_String(entityDefs.getStrId("DEF_ENTITIES_PIG"), "id")
                    tileEntityTag["SpawnData"] = tag()
                    if entity:
                        for k, v in entity.iteritems():
                            tileEntityTag["SpawnData"][k] = deepcopy(v)
                    else:
                        tileEntityTag["SpawnData"].add(spawn_id)
                    return True
            return False

        def createBaseStruct(tileEntityID, tileEntityTag, **kw):
            defId = self.getDefId(tileEntityID)

            for name, tag, value in self.baseStructures[tileEntityID]:
                if not handleSpecialStruct(tileEntityTag, defId, name, tag, **kw):
                    tileEntityTag[name] = tag(value) if value is not None else tag()
            return True

        def getNewId(oldId):
            if oldId not in self._oldToDefIds:
                return oldId
            item = self.defsIds.get_def(self._oldToDefIds[oldId])
            if item is None:
                return oldId
            return item.get("idStr", oldId)

        tileEntityTag = nbt.TAG_Compound()
        if convertOld:
            tileEntityID = getNewId(tileEntityID)
        tileEntityTag["id"] = nbt.TAG_String(tileEntityID)
        createBaseStruct(tileEntityID, tileEntityTag, **kw)

        TileEntity.setpos(tileEntityTag, pos)
        return tileEntityTag

    def copyWithOffset(self, tileEntity, copyOffset, staticCommands, moveSpawnerPos, first, cancelCommandBlockOffset=False):
        # You'll need to use this function twice
        # The first time with first equals to True
        # The second time with first equals to False
        eTag = deepcopy(tileEntity)
        eTag['x'] = nbt.TAG_Int(tileEntity['x'].value + copyOffset[0])
        eTag['y'] = nbt.TAG_Int(tileEntity['y'].value + copyOffset[1])
        eTag['z'] = nbt.TAG_Int(tileEntity['z'].value + copyOffset[2])

        def num(x):
            try:
                return int(x)
            except ValueError:
                return float(x)

        def coordX(x, argument):
            if first:
                x = str(num(x)) + '!' + str(num(x) + copyOffset[0])
            elif argument and x.find("!") >= 0:
                x = x[x.index("!") + 1:]
                x = str(num(x) + copyOffset[0])
            elif not argument and x.find("!") >= 0:
                x = x[:x.index("!")]
            return x

        def coordY(y, argument):
            if first:
                y = str(num(y)) + '!' + str(num(y) + copyOffset[1])
            elif argument and y.find("!") >= 0:
                y = y[y.index("!") + 1:]
                y = str(num(y) + copyOffset[1])
            elif not argument and y.find("!") >= 0:
                y = y[:y.index("!")]
            return y

        def coordZ(z, argument):
            if first:
                z = str(num(z)) + '!' + str(num(z) + copyOffset[2])
            elif argument and z.find("!") >= 0:
                z = z[z.index("!") + 1:]
                z = str(num(z) + copyOffset[2])
            elif not argument and z.find("!") >= 0:
                z = z[:z.index("!")]
            return z

        def coords(x, y, z, argument):
            if x[0] != "~":
                x = coordX(x, argument)
            if y[0] != "~":
                y = coordY(y, argument)
            if z[0] != "~":
                z = coordZ(z, argument)
            return x, y, z

        if self.getDefId(eTag["id"].value) == "DEF_TILEENTITIES_MOB_SPAWNER":
            mobs = []
            if 'SpawnData' in eTag:
                mob = eTag['SpawnData']
                if mob:
                    mobs.append(mob)
            if 'SpawnPotentials' in eTag:
                potentials = eTag['SpawnPotentials']
                for p in potentials:
                    if 'properties' in p:
                        mobs.extend(p["Properties"])
                    elif 'Entity' in p:
                        mobs.extend(p["Entity"])

            for mob in mobs:
                # Why do we get a unicode object as tag 'mob'?
                if "Pos" in mob and mob != "Pos":
                    if first:
                        pos = Entity.pos(mob)
                        x, y, z = [str(part) for part in pos]
                        x, y, z = coords(x, y, z, moveSpawnerPos)
                        mob['Temp1'] = nbt.TAG_String(x)
                        mob['Temp2'] = nbt.TAG_String(y)
                        mob['Temp3'] = nbt.TAG_String(z)
                    elif 'Temp1' in mob and 'Temp2' in mob and 'Temp3' in mob:
                        x = mob['Temp1']
                        y = mob['Temp2']
                        z = mob['Temp3']
                        del mob['Temp1']
                        del mob['Temp2']
                        del mob['Temp3']
                        parts = []
                        for part in (x, y, z):
                            part = str(part)
                            part = part[13:len(part) - 2]
                            parts.append(part)
                        x, y, z = parts
                        pos = [float(p) for p in coords(x, y, z, moveSpawnerPos)]
                        Entity.setpos(mob, pos)

        if not cancelCommandBlockOffset and self.getDefId(eTag["id"].value) == "DEF_TILEENTITIES_COMMAND_BLOCK":
            command = eTag['Command'].value
            oldCommand = command

            def selectorCoords(selector):
                old_selector = selector
                try:
                    char_num = 0
                    new_selector = ""
                    dont_copy = 0
                    if len(selector) > 4:
                        if '0' <= selector[3] <= '9':
                            new_selector = selector[:3]
                            end_char_x = selector.find(',', 4, len(selector) - 1)
                            if end_char_x == -1:
                                end_char_x = len(selector) - 1
                            x = selector[3:end_char_x]
                            x = coordX(x, staticCommands)
                            new_selector += x + ','

                            end_char_y = selector.find(',', end_char_x + 1, len(selector) - 1)
                            if end_char_y == -1:
                                end_char_y = len(selector) - 1
                            y = selector[end_char_x + 1:end_char_y]
                            y = coordY(y, staticCommands)
                            new_selector += y + ','

                            end_char_z = selector.find(',', end_char_y + 1, len(selector) - 1)
                            if end_char_z == -1:
                                end_char_z = len(selector) - 1
                            z = selector[end_char_y + 1:end_char_z]
                            z = coordZ(z, staticCommands)
                            new_selector += z + ',' + selector[end_char_z + 1:]

                        else:
                            for char in selector:
                                if dont_copy != 0:
                                    dont_copy -= 1
                                else:
                                    if (char != 'x' and char != 'y' and char != 'z') or letter:
                                        new_selector += char
                                        if char == '[' or char == ',':
                                            letter = False
                                        else:
                                            letter = True

                                    elif char == 'x' and not letter:
                                        new_selector += selector[char_num:char_num + 2]
                                        char_x = char_num + 2
                                        end_char_x = selector.find(',', char_num + 3, len(selector) - 1)
                                        if end_char_x == -1:
                                            end_char_x = len(selector) - 1
                                        x = selector[char_x:end_char_x]
                                        dont_copy = len(x) + 1
                                        x = coordX(x, staticCommands)
                                        new_selector += x

                                    elif char == 'y' and not letter:
                                        new_selector += selector[char_num:char_num + 2]
                                        char_y = char_num + 2
                                        end_char_y = selector.find(',', char_num + 3, len(selector) - 1)
                                        if end_char_y == -1:
                                            end_char_y = len(selector) - 1
                                        y = selector[char_y:end_char_y]
                                        dont_copy = len(y) + 1
                                        y = coordY(y, staticCommands)
                                        new_selector += y

                                    elif char == 'z' and not letter:
                                        new_selector += selector[char_num:char_num + 2]
                                        char_z = char_num + 2
                                        end_char_z = selector.find(',', char_num + 3, len(selector) - 1)
                                        if end_char_z == -1:
                                            end_char_z = len(selector) - 1
                                        z = selector[char_z:end_char_z]
                                        dont_copy = len(z) + 1
                                        z = coordZ(z, staticCommands)
                                        new_selector += z
                                char_num += 1
                    else:
                        new_selector = old_selector

                except:
                    new_selector = old_selector
                finally:
                    return new_selector

            try:
                execute = False
                Slash = False
                if command[0] == "/":
                    command = command[1:]
                    Slash = True

                # Adjust command coordinates.
                words = command.split(' ')

                i = 0
                for word in words:
                    if word[0] == '@':
                        words[i] = selectorCoords(word)
                    i += 1

                if command.startswith('execute'):
                    stillExecuting = True
                    execute = True
                    saving_command = ""
                    while stillExecuting:
                        if Slash:
                            saving_command += '/'
                        x, y, z = words[2:5]
                        words[2:5] = coords(x, y, z, staticCommands)
                        if words[5] == 'detect':
                            x, y, z = words[6:9]
                            words[6:9] = coords(x, y, z, staticCommands)
                            saving_command += ' '.join(words[:9])
                            words = words[9:]
                        else:
                            saving_command += ' '.join(words[:5])
                            words = words[5:]
                        command = ' '.join(words)
                        saving_command += ' '
                        Slash = False
                        if command[0] == "/":
                            command = command[1:]
                            Slash = True
                        words = command.split(' ')
                        if not command.startswith('execute'):
                            stillExecuting = False

                if (command.startswith('tp') and len(words) == 5) or command.startswith(
                        'particle') or command.startswith('replaceitem block') or (
                            command.startswith('spawnpoint') and len(words) == 5) or command.startswith('stats block') or (
                            command.startswith('summon') and len(words) >= 5):
                    x, y, z = words[2:5]
                    words[2:5] = coords(x, y, z, staticCommands)
                elif command.startswith('blockdata') or command.startswith('setblock') or (
                            command.startswith('setworldspawn') and len(words) == 4):
                    x, y, z = words[1:4]
                    words[1:4] = coords(x, y, z, staticCommands)
                elif command.startswith('playsound') and len(words) >= 6:
                    x, y, z = words[3:6]
                    words[3:6] = coords(x, y, z, staticCommands)
                elif command.startswith('clone'):
                    x1, y1, z1, x2, y2, z2, x, y, z = words[1:10]
                    x1, y1, z1 = coords(x1, y1, z1, staticCommands)
                    x2, y2, z2 = coords(x2, y2, z2, staticCommands)
                    x, y, z = coords(x, y, z, staticCommands)

                    words[1:10] = x1, y1, z1, x2, y2, z2, x, y, z
                elif command.startswith('fill'):
                    x1, y1, z1, x2, y2, z2 = words[1:7]
                    x1, y1, z1 = coords(x1, y1, z1, staticCommands)
                    x2, y2, z2 = coords(x2, y2, z2, staticCommands)

                    words[1:7] = x1, y1, z1, x2, y2, z2
                elif command.startswith('spreadplayers'):
                    x, z = words[1:3]
                    if x[0] != "~":
                        x = coordX(x, staticCommands)
                    if z[0] != "~":
                        z = coordZ(z, staticCommands)

                    words[1:3] = x, z
                elif command.startswith('worldborder center') and len(words) == 4:
                    x, z = words[2:4]
                    if x[0] != "~":
                        x = coordX(x, staticCommands)
                    if z[0] != "~":
                        z = coordZ(z, staticCommands)

                    words[2:4] = x, z
                if Slash:
                    command = '/'
                else:
                    command = ""
                command += ' '.join(words)

                if execute:
                    command = saving_command + command
                eTag['Command'].value = command
            except:
                eTag['Command'].value = oldCommand

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
            if "maxItems" in item and isinstance(item["maxItems"], int):
                self.maxItems[idStr] = item["maxItems"]
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

    def Create(self, entityID, pos=(0, 0, 0), convertOld=True, **kw):
        def getNewId(oldId):
            if oldId not in self._oldToDefIds:
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


# pcm1k - something should be done with this
class PocketEntityDefs(EntityDefs):
    unknown_entity_top = UNKNOWN_ENTITY_MASK + 0
    entityList = {"Chicken": 10,
                  "Cow": 11,
                  "Pig": 12,
                  "Sheep": 13,
                  "Wolf": 14,
                  "Villager": 15,
                  "Mooshroom": 16,
                  "Squid": 17,
                  "Rabbit": 18,
                  "Bat": 19,
                  "Iron Golem": 20,
                  "Snow Golem": 21,
                  "Ocelot": 22,
                  "Horse": 23,
                  "Donkey": 24,
                  "Mule": 25,
                  "SkeletonHorse": 26,
                  "ZombieHorse": 27,
                  "PolarBear": 28,
                  "Zombie": 32,
                  "Creeper": 33,
                  "Skeleton": 34,
                  "Spider": 35,
                  "Zombie Pigman": 36,
                  "Slime": 37,
                  "Enderman": 38,
                  "Silverfish": 39,
                  "Cave Spider": 40,
                  "Ghast": 41,
                  "Magma Cube": 42,
                  "Blaze": 43,
                  "Zombie Villager": 44,
                  "Witch": 45,
                  "StraySkeleton": 46,
                  "Hust": 47,
                  "WitherSkeleton": 48,
                  "Guardian": 49,
                  "ElderGuardian": 50,
                  "WitherBoss": 52,
                  "EnderDragon": 53,
                  "Shulker": 54,
                  "Endermite": 55,
                  "Player": 63,
                  "Item": 64,
                  "PrimedTnt": 65,
                  "FallingSand": 66,
                  "ThrownExpBottle": 68,
                  "XPOrb": 69,
                  "EyeOfEnderSignal": 70,
                  "EnderCrystal": 71,
                  "ShulkerBullet": 76,
                  "Fishing Rod Bobber": 77,
                  "DragonFireball": 79,
                  "Arrow": 80,
                  "Snowball": 81,
                  "Egg": 82,
                  "Painting": 83,
                  "MinecartRideable": 84,
                  "Fireball": 85,
                  "ThrownPotion": 86,
                  "ThrownEnderpearl": 87,
                  "LeashKnot": 88,
                  "WitherSkull": 89,
                  "Boat": 90,
                  "Lightning": 93,
                  "Blaze Fireball": 94,
                  "AreaEffectCloud": 95,
                  "Minecart with Hopper": 96,
                  "Minecart with TNT": 97,
                  "Minecart with Chest": 98,
                  "LingeringPotion": 101}

    def getNumId(self, v):
        """Returns the numeric ID of an entity, or a generated one if the entity is not known.
        The generated one is generated like this: 'UNKNOWN_ENTITY_MASK + X', where 'X' is a number.
        The first unknown entity will have the numerical ID 1001, the second one 1002, and so on.
        :v: the entity string ID to search for."""
        id = self.getId(v)
        if not isinstance(id, int) and v not in self.entityList:
            id = self.unknown_entity_top + 1
            self.entityList[v] = self.entityList['Entity %s'%id] = id
            self.unknown_entity_top += 1
        return id


class TileEntity(object):
    # trying to keep backwards compatibility
    _entityDefs = TileEntityDefs(None)

    baseStructures = {}
    stringNames = {}
    knownIDs = []
    maxItems = {}
    slotNames = {}

    @classmethod
    def _updateGlobal(cls, entityDefs):
        cls._entityDefs = entityDefs
        cls.baseStructures = entityDefs.baseStructures
        cls.stringNames = entityDefs.stringNames
        cls.knownIDs = entityDefs.knownIDs
        cls.maxItems = entityDefs.maxItems
        cls.slotNames = entityDefs.slotNames

    @classmethod
    def Create(cls, tileEntityID, pos=(0, 0, 0), defsIds=None, **kw):
        if defsIds is not None and defsIds is not cls._entityDefs.defsIds:
            # redirect to the correct TileEntityDefs object
            cls._updateGlobal(getTileEntityDefs(defsIds))
        return cls._entityDefs.Create(tileEntityID, pos=pos, convertOld=True, **kw)

    @classmethod
    def copyWithOffset(cls, tileEntity, copyOffset, staticCommands, moveSpawnerPos, first, cancelCommandBlockOffset=False, defsIds=None):
        if defsIds is not None and defsIds is not cls._entityDefs.defsIds:
            # redirect to the correct TileEntityDefs object
            cls._updateGlobal(getTileEntityDefs(defsIds))
        return cls._entityDefs.copyWithOffset(tileEntity, copyOffset, staticCommands, moveSpawnerPos, first, cancelCommandBlockOffset=cancelCommandBlockOffset)

    @classmethod
    def pos(cls, tag):
        return [tag[a].value for a in 'xyz']

    @classmethod
    def setpos(cls, tag, pos):
        for a, p in zip('xyz', pos):
            tag[a] = nbt.TAG_Int(p)


class Entity(object):
    # trying to keep backwards compatibility
    _entityDefs = TileEntityDefs(None)

    entityList = {}
    monsters = []
    maxItems = {}

    @classmethod
    def _updateGlobal(cls, entityDefs):
        cls._entityDefs = entityDefs
        cls.entityList = entityDefs.entityList
        cls.monsters = entityDefs.monsters
        cls.maxItems = entityDefs.maxItems

    @classmethod
    def Create(cls, entityID, pos=(0, 0, 0), **kw):
        return cls._entityDefs.Create(entityID, pos=pos, convertOld=True, **kw)

    @classmethod
    def copyWithOffset(cls, entity, copyOffset, regenerateUUID=False):
        return cls._entityDefs.copyWithOffset(entity, copyOffset, regenerateUUID=regenerateUUID)

    @classmethod
    def getId(cls, v, default="No ID"):
        return cls._entityDefs.getId(v, default=default)

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


_tileEntityDefsCache = {}
_entityDefsCache = {}

def getTileEntityDefs(defsIds, forceNew=False):
    entityDefs = getBaseDefs(defsIds, TileEntityDefs, TileEntity._entityDefs, _tileEntityDefsCache, forceNew)
    TileEntity._updateGlobal(entityDefs)
    return entityDefs

def getEntityDefs(defsIds, forceNew=False):
    entityDefs = getBaseDefs(defsIds, EntityDefs, Entity._entityDefs, _entityDefsCache, forceNew)
    Entity._updateGlobal(entityDefs)
    return entityDefs


class TileTick(object):
    @classmethod
    def pos(cls, tag):
        return [tag[a].value for a in 'xyz']


class InvalidEntity(ValueError):
    pass


class InvalidTileEntity(ValueError):
    pass
