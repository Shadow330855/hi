#!/user/bin/env python

from cardList import getCards, getNodes
import config, json, asyncio, math, time, random, os

"""Extra functions that work better in their own file"""


def initData():
    global cardList
    cardList = getCards()
    global nodeList
    nodeList = getNodes()


# Retrieve account information
def getPlyData(ply):  # takes a discord user object, not game object
    try:
        with open('player_data/' + str(ply.id) + '.txt', 'r') as json_file:
            return json.loads(json_file.read())
    except:
        return None


# Currently unused function to give all players $100
def theHandout():
    for files in os.listdir('player_data'):
        with open('player_data/' + str(files), 'r') as json_file:
            fileContents = json.loads(json_file.read())
        fileContents['money'] += 100
        with open('player_data/' + str(files), 'w') as outfile:
            json.dump(fileContents, outfile)
    print("Gave each player $100.")


async def mechMessage(ctx, msg):
    """Handles messaging outside of bot files. (necessary?)
    ctx should be a channel."""
    await ctx.send(msg)


# Handles a Node entering the field
async def nodeETB(ply, nodeName):
    nodeObj = nodeList[nodeName.lower()]
    for func in nodeObj.funcs:
        if func.trigger_type == "ETB":
            await func.func(ply, ply.opponent, None, ply)
    ply.energy = ply.energy + nodeObj.energy


# Player sacrificed a node as part of an ability (for health)
async def sacNode(ply, enemy, index):  # Returns the node OBJECT, not the name.
    removedNode = nodeList[ply.nodes[index].lower()]
    for func in removedNode.funcs:
        if func.trigger_type == "LTB":
            await func.func(ply, enemy, None, ply)
    ply.nodes.remove(ply.nodes[index])
    healthToGain = abs(round(0.1 * ply.hunger * removedNode.energy))
    if 'Feast' not in ply.nodes and 'Feast' not in enemy.nodes:  # card...specific......
        ply.lifeforce += healthToGain
    ply.energy -= removedNode.energy
    await add_to_trigger_queue("SAC", ply, removedNode)
    return removedNode


# Player milled a card for health
async def millCard(ply):
    poppedCard = ply.deck.pop()
    cost = cardList[poppedCard.lower()].cost
    lifeToGain = abs(round(0.1 * ply.desperation * cost))
    ply.lifeforce += lifeToGain
    await add_to_trigger_queue("MILL", ply, None)
    return poppedCard, lifeToGain


# Player activated a node
async def activateNode(nodeName, activePlayerObj, opponentObj):
    playedObject = nodeList[nodeName.lower()]
    await playedObject.func(activePlayerObj, opponentObj) or []


# Get player object from a discord ID string
def discordUserToPlayerObj(playerID):
    # Returns the player object for the searched player ID
    for game in config.matches:
        if config.matches[game].challenger == playerID:
            return config.matches[game].chalObj
        elif config.matches[game].defender == playerID:
            return config.matches[game].defObj
        else:
            return None


# Get discord user object from a player object
def playerObjToDiscordID(playerObj):
    # Returns the player object for the searched player ID
    for game in config.matches:
        if config.matches[game].chalObj == playerObj:
            return config.matches[game].challenger
        elif config.matches[game].defObj == playerObj:
            return config.matches[game].defender
        else:
            return None


# takes a TCGame object
def isGameRunning(match):
    if match.challenger in config.matches.keys() or match.defender in config.matches.keys():
        return True
    else:
        return False


# Game ended. Takes the loser's discord ID
async def gameOver(loserID):  # get ONLY discord ID of LOSER
    loserObj = discordUserToPlayerObj(loserID)
    winnerID = playerObjToDiscordID(loserObj.opponent)
    bot = loserObj.bot
    ctx = loserObj.ctx

    loser = await ctx.message.guild.fetch_member(loserID)
    winner = await ctx.message.guild.fetch_member(winnerID)

    if winner.id in config.matches:
        matchWager = config.matches[winner.id].wager
        matchTime = config.matches[winner.id].startTime
        timedOut = config.matches[winner.id].timedOut
        del config.matches[winner.id]
    elif loser.id in config.matches:
        matchWager = config.matches[loser.id].wager
        matchTime = config.matches[loser.id].startTime
        timedOut = config.matches[loser.id].timedOut
        del config.matches[loser.id]
    await mechMessage(ctx.message.channel,
                           ":medal: " + loser.name + " just lost to " + winner.name + " in discordTCG!")
    grantMoney(winner.id, matchWager)
    grantMoney(loser.id, -1 * matchWager)
    # random money pickup chance
    secondsElapsed = time.time() - matchTime
    if secondsElapsed > 127 and not timedOut:
        if random.randint(0, 4) % 2 == 1:
            givenMoney = random.randint(15, 40)
            grantMoney(winner.id, givenMoney)
            await mechMessage(winner, "You found $" + str(givenMoney) + " lying in your opponent's ashes.")


# Give someone an amount of a card (takes their discord ID)
def grantCard(plyID, card, amount):
    with open('player_data/' + str(plyID) + '.txt', 'r') as json_file:
        fileContents = json.loads(json_file.read())

    foundCard = False
    for cards in fileContents['collection']:
        if card.lower() == cards.lower():
            foundCard = True
            fileContents['collection'][cards] += int(amount)
    if foundCard == False:
        fileContents['collection'][cardList[card.lower()].name] = 1

    with open('player_data/' + str(plyID) + '.txt', 'w') as outfile:
        json.dump(fileContents, outfile)


# Get someone's $  (takes discord ID)
def getBal(plyID):
    with open('player_data/' + str(plyID) + '.txt', 'r') as json_file:
        return json.loads(json_file.read())['money']


# Give some money (Takes discord ID)
def grantMoney(plyID, amount):
    with open('player_data/' + str(plyID) + '.txt', 'r') as json_file:
        fileContents = json.loads(json_file.read())

    fileContents['money'] += amount

    with open('player_data/' + str(plyID) + '.txt', 'w') as outfile:
        json.dump(fileContents, outfile)


# Get someone's amount of packs (takes discord ID)
def getPacks(plyID):
    with open('player_data/' + str(plyID) + '.txt', 'r') as json_file:
        return json.loads(json_file.read())['packs']


# Grants someone some packs (takes discord ID)
def grantPacks(plyID, amount):
    with open('player_data/' + str(plyID) + '.txt', 'r') as json_file:
        fileContents = json.loads(json_file.read())

    fileContents['packs'] += amount

    with open('player_data/' + str(plyID) + '.txt', 'w') as outfile:
        json.dump(fileContents, outfile)


# Automates damage dealing
async def damage(playerObj, amt):
    playerObj.lifeforce -= amt
    await add_to_trigger_queue("DAMAGE", playerObj, amt)
    if playerObj.lifeforce <= 0:
        await gameOver(playerObjToDiscordID(playerObj))  # no ids
        return


# Automates lifegain
async def heal(playerObj, amt):
    playerObj.lifeforce += amt
    await add_to_trigger_queue("HEAL", playerObj, amt)
    if playerObj.lifeforce <= 0:
        await gameOver(playerObjToDiscordID(playerObj))
        return


def node_name_to_object(name: str):
    try:
        return nodeList[name.lower()]
    except: # TODO: less broad
        return None


async def add_to_trigger_queue(trigger, playerObj, dataPassed):
    """Adds a trigger to a player's trigger queue (nodesToTrigger).
    dataPassed is the node destroyed/created, damage dealt/healed, etc
    playerObj is the player who was affected. ONLY the opponent player's nodes will trigger.
    Make sure to print out using the new mechMessage() so people know what was triggered.
    Could also use this to log!
    Possible triggers: "HEAL", "DAMAGE", "BURN", "MILL", "SAC", "NODESPAWN", "PLAYED_CARD", "TURN_START"
    Also, "ETB" and "LTB" but they are not handled here. (nodeETB(), sacNode())
    All currently only trigger your opponent's Nodes. Eventually do this specific for each type.
    """

    print(f'Add to trigger queue {trigger} from {playerObj.name}')
    # This try is to ignore the trigger from initial card draw
    try:
        for node in playerObj.nodes:
            nodeObj = nodeList[node.lower()]
            for node_function in nodeObj.funcs:
                print(f'Node function: {node_function}')
                if node_function.trigger_type == trigger:
                    playerObj.nodesToTrigger.append([node_function.func, dataPassed, "self", node.lower()])
        for node in playerObj.opponent.nodes:
            nodeObj = nodeList[node.lower()]
            for node_function in nodeObj.funcs:
                if node_function.trigger_type == trigger:
                    playerObj.opponent.nodesToTrigger.append([node_function.func, dataPassed, "enemy", node.lower()])
    except AttributeError as e:
        return

    if len(playerObj.nodesToTrigger) > 0:
        await trigger_queued_triggers(playerObj)
    if len(playerObj.opponent.nodesToTrigger) > 0:
        await trigger_queued_triggers(playerObj.opponent)


async def trigger_queued_triggers(ply):
    """This function actually acts on the queued triggers for a player."""
    print(ply.nodesToTrigger)
    opponent = ply.opponent
    while len(ply.nodesToTrigger) > 0:
        triggered = ply.nodesToTrigger.pop()
        print(triggered)
        went_through = await triggered[0](ply, opponent, triggered[1],
                                                                     triggered[2]) or []

        # If conditionals fail in a Node, they should explicitly return False. Otherwise, they'll be considered triggered.
        if went_through != False:
            node_name = nodeList[triggered[3].lower()].name
            ply.log.append(ply.name + "'s " + node_name + " was triggered.")

    ply.nodesToTrigger = []
