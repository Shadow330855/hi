#!/user/bin/env python

from cardList import addCard
import mechanics

#Simple variables
NAME = "Pleasant Memories"
COST = 5
RARITY = 'U'
DESC = "Spawn a Nostalgia Node."
TARGETS = None
TYPE = "NodeGen"

#What happens when you play it
async def playFunc(ply, enemy, target):
	await ply.addNode( 'Nostalgia' )
	
addCard( NAME, COST, RARITY, DESC, TARGETS, TYPE, playFunc )

