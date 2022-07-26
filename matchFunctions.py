#!/user/bin/env python

import discord
from discord.ext import commands
from discord.ext.commands import Bot
from discord.utils import get
import asyncio
import os, sys, random
from classes import cardbase, gamebase, playerbase
import mechanics, config
import json

# For cogs when needed
mechanics.initData()
startup_extensions = ['cogs.infocommands', 'cogs.deckbuilding', 'cogs.collecting']
config.matches = {}

# Bot setup
TOKEN = config.TOKEN
activity = discord.Game(name=f"Version {config.VERSION}. Use =help!")
bot = commands.Bot(command_prefix='=', activity=activity)


# Load extensions
@bot.event
async def on_ready():
    for extension in startup_extensions:
        try:
            bot.load_extension(extension)
            print("Successfully loaded " + str(extension) + "!")
        except Exception as e:
            print("Extension load failed: " + str(extension) + ".\nMessage: " + str(e))


# Send hand function
async def sendHand(player, playerObj, ctx):
    # delete last hand sent
    if playerObj.lastHandDM:
        await playerObj.lastHandDM.delete()

    # send hand
    stringSend = ""
    for cards in playerObj.hand:
        stringSend += str(mechanics.cardList[cards.lower()]) + "\n"
    playerObj.lastHandDM = await player.send("[-----Hand-----]\n" + stringSend + "\n\n")


# print and reset player logs, then activate all triggered abilities
async def printLogs(match, ctx):
    playerOneObj = match.chalObj
    playerTwoObj = match.defObj

    strToSend = ""
    for logs in playerOneObj.log:
        strToSend += logs + '\n'
    if len(playerOneObj.log) > 0:
        await ctx.message.channel.send(strToSend)
    playerOneObj.log = []

    strToSend = ""
    for logs in playerTwoObj.log:
        strToSend += logs + '\n'
    if len(playerTwoObj.log) > 0:
        await ctx.message.channel.send(strToSend)
    playerTwoObj.log = []


# Active player played a card
async def playCard(match, activePlayer, activePlayerObj, opponent, opponentObj, cardName, targets, ctx):
    playedObject = mechanics.cardList[cardName.lower()]

    # Pay health if possible
    if activePlayerObj.lifeforce <= playedObject.cost:
        await ctx.message.channel.send("You don't have enough lifeforce for that card.")
        return
    else:
        activePlayerObj.lifeforce -= playedObject.cost  # doesn't use damage function cause it shouldn't trigger as damage

    if activePlayerObj.lifeforce <= 0:
        await gameOver(activePlayer.id)
        return

    # Remove card from hand
    for card in activePlayerObj.hand:
        if card.lower() == cardName:
            activePlayerObj.hand.remove(card)
            break

    # Play the card (assuming already got proper targets)
    await playedObject.func(activePlayerObj, opponentObj,
                                 targets) or []  # the or [] does something undefined but makes it work.
    await ctx.message.channel.send(activePlayer.name + " played " + str(playedObject) + "\n\n")
    await mechanics.add_to_trigger_queue("PLAYED_CARD", activePlayerObj, playedObject.name)

    # check if game still exists
    if not mechanics.isGameRunning(match):
        return

    # Send hand & messages
    activePlayerObj.cardsThisTurn += 1
    await sendHand(activePlayer, activePlayerObj, ctx)

    await printLogs(match, ctx)
    if not match.gameMessage == None:
        await match.gameMessage.delete()
    match.gameMessage = await ctx.message.channel.send(
        str(activePlayerObj) + "\n\n" + str(opponentObj) + "\nCommands: play, concede, pass, info, mill")
    return True


async def getTarget(playedObject, activePlayerObj, activePlayer, otherPlayerObj, ctx):
    targetEmojis = ['0⃣', '1⃣', '2⃣', '3⃣', '4⃣', '5⃣', '6⃣', '7⃣', '8⃣', '9⃣', '🔟']

    def checkTarget(reaction, user):
        return user == activePlayer and str(reaction) in targetEmojis

    if playedObject.targets == None:
        return None
    elif playedObject.targets == "ENEMY_NODE":
        # React to self up to amount of enemy nodes (if none, then continue big loop)
        if len(otherPlayerObj.nodes) == 0:
            await ctx.message.channel.send("No nodes to target.")
            return -1  # if False, continue

        msg = await ctx.message.channel.send("Use reactions to indicate which of your opponent's Nodes to target.")
        for i in range(len(otherPlayerObj.nodes)):
            await msg.add_reaction(targetEmojis[i + 1])

        # Wait for reaction from that list
        try:
            reaction, user = await bot.wait_for('reaction_add', check=checkTarget, timeout=200.0)
        except asyncio.TimeoutError:
            await ctx.message.channel.send("Timed out waiting for target. Defaulting to first target.")
            return 0

        thisTarget = targetEmojis.index(str(reaction.emoji)) - 1
        return thisTarget
    elif playedObject.targets == "FRIENDLY_NODE":
        # React to self up to amount of friendly nodes (if none, then continue big loop)
        if len(activePlayerObj.nodes) == 0:
            await ctx.message.channel.send("No nodes to target.")
            return -1

        msg = await ctx.message.channel.send("Use reactions to indicate which of your Nodes to target.")
        for i in range(len(activePlayerObj.nodes)):
            await msg.add_reaction(targetEmojis[i + 1])

        # Wait for reaction from that list
        try:
            reaction, user = await bot.wait_for('reaction_add', check=checkTarget, timeout=200.0)
        except asyncio.TimeoutError:
            await ctx.message.channel.send("Timed out waiting for target. Defaulting to first target.")
            return 0

        thisTarget = targetEmojis.index(str(reaction.emoji)) - 1
        return thisTarget

    elif playedObject.targets == "PLAYER":
        msg = await ctx.message.channel.send(
            "Use reactions to indicate which player to target (1 is yourself, 2 is your opponent).")
        for i in range(2):
            await msg.add_reaction(targetEmojis[i + 1])

        try:
            reaction, user = await bot.wait_for('reaction_add', check=checkTarget, timeout=200.0)
        except asyncio.TimeoutError:
            await ctx.message.channel.send("Timed out waiting for target. Defaulting to first target.")
            return 0

        thisTarget = targetEmojis.index(str(reaction.emoji)) - 1
        return thisTarget


# New round in a match started
async def startRound(match, activePlayer, activePlayerObj, otherPlayer, otherPlayerObj, ctx):
    # check if game still exists
    if not mechanics.isGameRunning(match):
        return
    # check if milled out when drawing a card (maybe condense this chunk somehow)
    if not (await activePlayerObj.drawCard()):
        await ctx.message.channel.send(activePlayer.name + " milled out!")
        await mechanics.gameOver(activePlayer.id)
        return

    # Energy costs (oooh actual phase orders are showing c:)
    await mechanics.heal(activePlayerObj, activePlayerObj.energy)

    # check if game still exists
    if not mechanics.isGameRunning(match):
        return

    # Activate all of active player's nodes/initialize turn-based vars
    activePlayerObj.newTurn()
    otherPlayerObj.newTurn()
    await activePlayerObj.newMyTurn()

    # check if game still exists
    if not mechanics.isGameRunning(match):
        return

    # Send the info
    await ctx.message.channel.send(activePlayer.name + "'s turn.")
    if not match.gameMessage == None:
        await match.gameMessage.delete()
    await printLogs(match, ctx)
    match.gameMessage = await ctx.message.channel.send(
        str(activePlayerObj) + "\n\n" + str(otherPlayerObj) + "\nCommands: play, concede, pass, info, mill")

    await sendHand(activePlayer, activePlayerObj, ctx)

    # Make sure it's a game command
    def check_command(msg):
        return msg.author == activePlayer and (msg.content.lower().startswith('play') or msg.content.lower().startswith(
            'concede') or msg.content.lower().startswith('pass') or msg.content.lower().startswith(
            'info') or msg.content.lower().startswith('mill'))

    # Wait for active player's command.
    while True:
        # check if game still exists
        if not mechanics.isGameRunning(match):
            return

        # Act within 500 seconds or game is lost
        try:
            messageOriginal = await bot.wait_for('message', check=check_command, timeout=config.TURN_TIMEOUT)
            message = messageOriginal.content.lower().split(' ', 1)
        except asyncio.exceptions.TimeoutError:
            await ctx.message.channel.send("Game timed out!")
            match.timedOut = True
            await mechanics.gameOver(activePlayer.id)
            break

        if message[0] == 'info':
            if not match.gameMessage == None:
                await match.gameMessage.delete()
            match.gameMessage = await ctx.message.channel.send(
                str(activePlayerObj) + "\n\n" + str(otherPlayerObj) + "\nCommands: play, concede, pass, info, mill")
            continue
        elif message[0] == 'play':  # The big one

            # Ensure it's in hand
            if not any(message[1] in x.lower() for x in activePlayerObj.hand):
                await ctx.message.channel.send("Played a card not in your hand.")
                continue

            # Get proper targets
            try:
                playedObject = mechanics.cardList[message[1].lower()]
            except KeyError:
                await ctx.message.channel.send("That card doesn't exist!")
                continue

            thisTarget = await getTarget(playedObject, activePlayerObj, activePlayer, otherPlayerObj, ctx)
            print(thisTarget)
            if thisTarget == -1:
                continue

            # Check if node generator (for 1 per turn limit)
            if playedObject.cardtype == "NodeGen":
                if activePlayerObj.playedNode:
                    await ctx.message.channel.send("You already spawned a Node this turn.")
                    continue
                else:
                    activePlayerObj.playedNode = True
            await playCard(match, activePlayer, activePlayerObj, otherPlayer, otherPlayerObj, message[1],
                                thisTarget, ctx)
            continue

        elif message[0] == 'pass':
            await startRound(match, otherPlayer, otherPlayerObj, activePlayer, activePlayerObj, ctx)
            break
        elif message[0] == 'mill':
            if activePlayerObj.milled == True:
                await ctx.message.channel.send("You already milled a card this turn.")
                continue
            elif len(activePlayerObj.deck) <= 0:
                await ctx.message.channel.send("You have no cards to mill.")
                continue
            else:
                activePlayerObj.milled = True
                poppedCard, lifeToGain = await mechanics.millCard(activePlayerObj)
                await ctx.message.channel.send(
                    activePlayerObj.name + " milled " + poppedCard + " for " + str(lifeToGain) + " health.")
                continue
        elif message[0] == 'concede':
            await ctx.message.channel.send(activePlayer.name + " conceded.")
            await mechanics.gameOver(activePlayer.id)
            return


# Challenge someone and initialize the fight
@bot.command(pass_context=True)
async def challenge(ctx, target: discord.Member = None, *args):
    """Challenge a friend to discordTCG! =challenge <@user> <wager>"""

    challengerID = ctx.message.author.id

    # Make sure neither player is in a game currently
    if challengerID in config.matches or target.id in config.matches:
        await ctx.message.channel.send("A player is already in a match.")
        return

    # Dont challenge yourself man
    if ctx.message.author == target:
        await ctx.message.channel.send("You can't challenge yourself, silly!")
        return

    # Have challenged guy accept
    await ctx.message.channel.send(target.name + ", you've been challenged to a discordTCG match! Type 'accept' to accept.")

    def check(m):
        return m.author == target and m.content == 'accept'

    try:
        await bot.wait_for('message', check=check, timeout=config.CHALLENGE_TIMEOUT)
    except asyncio.exceptions.TimeoutError:
        await ctx.message.channel.send(ctx.message.author.name + ", your challenge was not accepted :(")
        return

    # check again here for duplicate accepts
    if challengerID in config.matches or target.id in config.matches:
        await ctx.message.channel.send("A player is already in a match.")
        return

    # Get player data
    challengerDeck = mechanics.getPlyData(ctx.message.author)
    defenderDeck = mechanics.getPlyData(target)
    if defenderDeck is None or challengerDeck is None:
        await ctx.message.channel.send("Both players aren't registered! Use =register.")
        return
    challengerDeck = challengerDeck['decks'][challengerDeck['selectedDeck']]
    defenderDeck = defenderDeck['decks'][defenderDeck['selectedDeck']]
    if len(challengerDeck) < config.DECK_SIZE_MINIMUM or len(defenderDeck) < config.DECK_SIZE_MINIMUM:
        await ctx.message.channel.send(
            "A player doesn't have at least " + str(config.DECK_SIZE_MINIMUM) + " cards in his or her deck.")
        return

    # Wager stuff
    try:
        wager = int(args[0])
        if mechanics.getBal(ctx.message.author.id) < wager or mechanics.getBal(target.id) < wager:
            await ctx.message.channel.send("A player doesn't have enough money for this wager!")
            return
        await ctx.message.channel.send("Wager set to $" + args[0] + "!")
    except:
        wager = 0

    # Initialize game
    config.matches[challengerID] = gamebase.TCGame(challengerID, target.id, wager)
    config.matches[challengerID].chalObj = playerbase.Player(ctx.message.author.name, challengerDeck, [], bot, ctx)
    config.matches[challengerID].defObj = playerbase.Player(target.name, defenderDeck, [], bot, ctx)
    config.matches[challengerID].chalObj.shuffle()
    config.matches[challengerID].defObj.shuffle()
    for i in range(config.STARTING_HAND_SIZE):
        await config.matches[challengerID].chalObj.drawCard()
        await config.matches[challengerID].defObj.drawCard()
    config.matches[challengerID].chalObj.opponent = config.matches[challengerID].defObj
    config.matches[challengerID].defObj.opponent = config.matches[challengerID].chalObj
    print('A match has started. ' + str(ctx.message.author.name) + ' vs ' + str(target.name) + '!')

    # Start round
    if random.randint(0, 1) == 0:
        config.matches[challengerID].chalObj.active = True
        config.matches[challengerID].defObj.energy += 1
        await startRound(config.matches[challengerID], ctx.message.author, config.matches[challengerID].chalObj,
                              target, config.matches[challengerID].defObj, ctx)
    else:
        config.matches[challengerID].defObj.active = True
        config.matches[challengerID].chalObj.energy += 1
        await startRound(config.matches[challengerID], target, config.matches[challengerID].defObj,
                              ctx.message.author, config.matches[challengerID].chalObj, ctx)


print("[-=-Loaded Cards-=-]\n")
for cards in mechanics.cardList:
    print(cards)
print("\n[-=-Loaded Nodes-=-]\n")
for nodes in mechanics.nodeList:
    print(nodes)

bot.run(TOKEN)
