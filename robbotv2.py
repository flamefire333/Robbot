import os
import random
import csv
import discord
import copy
import threading
import asyncio
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

client = discord.Client()
bot = commands.Bot(command_prefix = "!")
safetyLock = threading.Lock()
spinLock = 0

class FakeChannel:
    def __init__(self, header, baseChannel):
        self.channel = baseChannel
        self.header = header
    async def send(self, message):
        await self.channel.send("---" + self.header + "---\n" + message)
        return 0

class FakePlayer:
    def __init__(self, name, baseChannel):
        self.name = name
        self.dm_channel = FakeChannel(name, baseChannel)
    async def create_dm(self):
        return 0

fakePlayers = dict()

def getFakePlayer(name, baseChannel):
    if name not in fakePlayers:
        fakePlayers[name] = FakePlayer(name, baseChannel)
    return fakePlayers[name]

async def doNothingCallback():
    return 0

async def doNothingCallbackWithArgs(a, b):
    return 0

class PromptsBarrier:
    def __init__(self, game, callback):
        self.prompts = []
        self.game = game
        self.count = 0
        self.callback = callback
    def addPrompt(self, prompt):
        self.prompts.append(prompt)
        self.prompts[-1].barrier = self
        self.count = self.count + 1
    async def triggerPrompts(self):
        for prompt in self.prompts:
            await prompt.sendPrompt()
    async def promptAnswered(self):
        self.count = self.count - 1
        if(self.count == 0):
            if self.game.promptBarrier == self:
                self.game.promptBarrier = None
            await self.callback()

class Prompt:
    def __init__(self, game, question):
        self.answered = False
        self.game = game
        self.question = question
    def setMember(self, member):
        self.member = member
    async def sendPrompt(self):
        await self.game.sendDM(member, self.question)

def getClosestChoice(needle, haystack):
    bestCount = 0
    bestChoice = None
    for h in haystack:
        if needle == h:
            return needle
        if len(needle) < len(h):
            if h.startswith(needle):
                bestChoice = h
                bestCount = bestCount + 1
    if(bestCount > 1):
        return None
    return bestChoice
        

class ChoosePrompt(Prompt):
    def __init__(self, game, exclude, question, choices, choiceLogic):
        rm = [c.lower() for c in choices]
        actualrm = []
        for m in rm:
            if m not in exclude:
                actualrm.append(m)
        self.choices = actualrm
        self.choiceLogic = choiceLogic
        Prompt.__init__(self, game, question)
    async def sendPrompt(self):
        await self.game.sendDM(self.member, self.question + "\n--CHOICES--\n" + ("\n".join(self.choices)))
    async def answer(self, answer):
        if(self.answered):
            await self.game.sendDM(self.member, "You have already answered")
            return
        chosen = getClosestChoice(answer, [c.lower() for c in self.choices])
        if chosen is not None:
            await self.game.sendDM(self.member, "Answer recieved")
            await self.choiceLogic(self.member.name, chosen)
            self.answered = True
            await self.barrier.promptAnswered()
        else:
            await self.game.sendDM(self.member, "Your answer was not a valid choice")

class ChooseMemberPrompt(ChoosePrompt):
    def __init__(self, game, exclude, question, choiceLogic):
        ChoosePrompt.__init__(self, game, exclude, question, game.getMemberNames(), choiceLogic)

class ChooseMemberInRolePrompt(ChoosePrompt):
    def __init__(self, game, role, exclude, question, choiceLogic):
        ChoosePrompt.__init__(self, game, exclude, question, game.getMemberNamesInRole(role), choiceLogic)

class YNPrompt(ChoosePrompt):
    def __init__(self, game, question, choiceLogic):
        ChoosePrompt.__init__(self, game, [], question, ["No", "Yes"], choiceLogic)

class Game:
    def __init__(self, channel_name):
        self.members = set()
        self.channel_name = channel_name
        self.channel = None
        self.roles = dict()
        self.promptBarrier = None
        self.gamePhase = 0
    def addMember(self, member):
        self.members.add(member)
    def removeMember(self, member):
        self.members.remove(member)
    def getMemberFromName(self, name):
        for m in self.members:
            if m.name.lower() == name.lower():
                return m
        return None
    def getMemberRole(self, member):
        return self.roles[member]
    def getMemberNames(self):
        return [member.name for member in self.members]
    def getLowerMemberNames(self):
        return [m.lower() for m in self.getMemberNames()]
    def getMembersInRole(self, role):
        answer = []
        for m in self.members:
            if role in self.roles[m]:
                answer.append(m)
        return answer
    def getMemberNamesInRole(self, role):
        return [m.name for m in self.getMembersInRole(role)]
    def setChannel(self, channel):
        self.channel = channel
    async def sendMessage(self, message):
        await self.channel.send(message)
        for m in self.members:
            if not isinstance(m, FakePlayer):
                await self.sendDM(m, message)
    async def sendMessageToChannel(self, channel, message):
        await channel.send(message)
    async def sendDM(self, member, message):
        print(member)
        await member.create_dm()
        await member.dm_channel.send(message)
    async def sendPromptToAllWithRole(self, role, prompt, callback):
        pb = PromptsBarrier(self, callback)
        for m in self.members:
            if role in self.roles[m]:
                p = copy.copy(prompt)
                p.setMember(m)
                pb.addPrompt(p)
        self.promptBarrier = pb
        await pb.triggerPrompts()
    async def sendPromptToAll(self, prompt, callback):
        pb = PromptsBarrier(self, callback)
        for m in self.members:
            p = copy.copy(prompt)
            p.setMember(m)
            pb.addPrompt(p)
        self.promptBarrier = pb
        await pb.triggerPrompts()
    async def sendPromptParasiteTo(self, member, prompt):
        prompt.setMember(member)
        self.promptBarrier.addPrompt(prompt)
        await prompt.sendPrompt()
    async def sendPromptTo(self, member, prompt):
        pb = PromptsBarrier(self, doNothingCallback)
        prompt.setMember(member)
        pb.addPrompt(prompt)
        self.promptBarrier = pb
        await pb.triggerPrompts()
    async def sendMessageToRole(self, role, message):
        roleMembers = self.getMembersInRole(role)
        for m in roleMembers:
            await self.sendDM(m, message)
    async def sendQueue(self, channel):
        qu = '\n - '.join(self.getMemberNames())
        await self.sendMessageToChannel(channel, "Queue:\n - " + qu)
    def assignRoles(self, roles):
        random.shuffle(roles)
        i = 0
        for f in self.members:
            self.roles[f] = roles[i]
            i = i + 1

class FakeArtistGame(Game):
    plainRole = 0
    fakerRole = 1
    async def vote(self, whoVoted, votedFor):
        if votedFor in self.fakerVotes:
            self.fakerVotes[votedFor] = self.fakerVotes[votedFor] + 1
        else:
            self.fakerVotes[votedFor] = 1
    async def startGame(self, channel):
        self.roles = dict()
        self.fakerVotes = dict()
        self.setChannel(channel)
        self.gamePhase = 1
        topicData = random.choice(topics)
        category = topicData[0]
        item = topicData[1]
        currID = 0
        roles = ([self.plainRole] * (len(self.members) - 1)) + ([self.fakerRole])
        roles = [[r] for r in roles]
        self.assignRoles(roles)
        await self.sendMessageToRole(self.plainRole, f'Category: {category}\nItem: {item}')
        await self.sendMessageToRole(self.fakerRole, f'You are the faker!\nCategory: {category}\nItem: ???')
        names = self.getMemberNames()
        random.shuffle(names)
        await self.sendMessage("Turn Order:\n" + "\n".join(names))
    async def printOutResults(self):
        votes = []
        for key in self.fakerVotes:
            votes.append(key + " has " + str(self.fakerVotes[key]) + " votes!")
        await self.sendMessage("\n".join(votes))
    async def endGame(self):
        self.gamePhase = 2
        q = f'Please vote for one of the following: ' + ", ".join(self.getMemberNames()) + " by replying with the name"
        await self.sendPromptToAll(ChooseMemberPrompt(self, [], q, self.vote), self.printOutResults)

class SecretHitlerGame(Game):
    liberalRole = 0
    fascistRole = 1
    hitlerRole = 2
    aliveRole = 3
    def getTermLimited(self):
        if len(self.turnOrder) <= 5:
            if self.lastChancellor is None:
                return []
            else:
                return [self.lastChancellor.name]
        else:
            data = []
            if self.lastChancellor is not None:
                data.append(self.lastChancellor.name)
            if self.lastPresident is not None:
                data.append(self.lastPresident.name)
            return data
    def getNonChancellorable(self):
        base = self.getTermLimited()
        if self.turnOrder[self.placardPosition].name not in base:
            base.append(self.turnOrder[self.placardPosition].name)
        return base
    def vote(self, whoVoted, votedFor):
        if votedFor in self.fakerVotes:
            self.fakerVotes[votedFor] = self.fakerVotes[votedFor] + 1
        else:
            self.fakerVotes[votedFor] = 1
    async def startGame(self, channel):
        playerCount = len(self.members)
        self.lastChancellor = None
        self.lastPresident = None
        self.voteTracker = 0
        self.playerCount = playerCount
        self.deck = ([self.fascistRole] * 11) + ([self.liberalRole] * 6)
        self.discard = []
        random.shuffle(self.deck)
        self.fascistPoliciesPassed = 0
        self.liberalPoliciesPassed = 0
        if(playerCount < 5 or playerCount > 10):
            await self.sendMessageToChannel(channel, "Wrong amount of players")
            return
        self.roles = dict()
        self.fakerVotes = dict()
        self.setChannel(channel)
        self.gamePhase = 1
        shouldInformHitler = False
        if(playerCount == 5 or playerCount == 6):
            shouldInformHitler = True
            roles = ([self.liberalRole] * (playerCount - 2)) + [self.fascistRole] + [self.hitlerRole]
        elif(playerCount == 7 or playerCount == 8):
            roles = ([self.liberalRole] * (playerCount - 3)) + ([self.fascistRole] * 2) + [self.hitlerRole]
        else:
            roles = ([self.liberalRole] * (playerCount - 4)) + ([self.fascistRole] * 3) + [self.hitlerRole]
        roles = [[r, self.aliveRole] for r in roles]
        self.assignRoles(roles)
        await self.sendMessageToRole(self.liberalRole, f'You are a liberal')
        fascInfo = self.getMemberNamesInRole(self.fascistRole)
        hitInfo = self.getMemberNamesInRole(self.hitlerRole)
        totalFascInfo = "--FASCISTS--\n" + ("\n".join(fascInfo)) + "\n--HITLER--\n" + hitInfo[0]
        await self.sendMessageToRole(self.fascistRole, f'You are a fascist\n' + totalFascInfo)
        if(shouldInformHitler):
            await self.sendMessageToRole(self.hitlerRole, f'You are the Secret Hitler\n' + totalFascInfo)
        else:
            await self.sendMessageToRole(self.hitlerRole, f'You are the Secret Hitler')
        players = list(self.members)
        random.shuffle(players)
        self.turnOrder = players
        await self.sendMessage("Turn Order:\n" + "\n".join([m.name for m in self.turnOrder]))
        self.placardPosition = 0
        await self.nominateChancellor()
    async def refillDeck(self):
        await self.sendMessage("Not enough cards, reshuffling in discard pile")
        self.deck = self.deck + self.discard
        self.discard = []
        random.shuffle(self.deck)
    async def presidentDeckInvestigation(self):
        await self.sendMessage("The president gets to investigate the top three agendas of the deck!")
        if(len(self.deck) < 3):
            await self.refillDeck()
        amountFascist = sum(self.deck[:3])
        amountLiberal = 3 - amountFascist
        await self.sendDM(self.turnOrder[self.placardPosition], "The top of the deck has " + str(amountFascist) + " fascist agendas and " + str(amountLiberal) + " liberal agendas.")
        await self.passPlacard()
    async def assassinate(self, voter, voted):
        await self.sendMessage("The president has assassinated " + str(voted))
        ind = 0
        for i in range(len(self.turnOrder)):
            if self.turnOrder[i].name == voted:
                ind = i
        if(self.hitlerRole in self.roles[self.turnOrder[ind]]):
            self.sendMessage(self.turnOrder[ind].name + " who was just killed was the secret hitler so liberals win!")
            return
        self.roles[self.turnOrder[ind]].remove(self.aliveRole)
        del self.turnOrder[ind]
        if self.placardPosition > ind:
            self.placardPosition = self.placardPosition - 1
        await self.sendMessage("Updated Turn Order:\n" + "\n".join([m.name for m in self.turnOrder]))
        await self.passPlacard()
    async def presidentShoot(self):
        await self.sendPromptTo(self.chancellor, ChooseMemberInRolePrompt(self, self.aliveRole, [], "Who do you want to assassinate?", self.assassinate))
    async def vetoYN(self, voter, voted):
        amountFascist = self.currentHandFascists
        amountLiberal = 2 - amountFascist
        if(voted == "yes"):
            self.discard = self.discard + ([self.liberalRole] * amountLiberal) + ([self.fascistRole] * amountFascist)
            await self.passPlacard()
        else:
            await self.cardPhaseChancellor(amountFascist, amountLiberal, False)
    async def handleVeto(self):
        await self.sendPromptTo(self.turnOrder[self.placardPosition], YNPrompt(self, "Would you like to accept the veto?", self.vetoYN))
    async def playPolicyPhase(self, voter, voted):
        if(voted == "veto"):
            await self.handleVeto()
            return
        elif(voted == "fascist"):
            self.currentHandFascists = self.currentHandFascists - 1
            self.discard = self.discard + [self.fascistRole]
        else:
            self.discard = self.discard + [self.liberalRole]
        if(self.currentHandFascists == 0):
            self.liberalPoliciesPassed = self.liberalPoliciesPassed + 1
            await self.sendMessage("A liberal policy has been played")
            await self.sendMessage("So far " + str(self.liberalPoliciesPassed) + " liberal policies have been passed and " + str(self.fascistPoliciesPassed) + " fascist policies have been passed.")
            if(self.liberalPoliciesPassed == 5):
                self.sendMessage("Liberals have won the game!")
            else:
                await self.passPlacard()
        else:
            self.fascistPoliciesPassed = self.fascistPoliciesPassed + 1
            await self.sendMessage("A fascist policy has been played")
            await self.sendMessage("So far " + str(self.liberalPoliciesPassed) + " liberal policies have been passed and " + str(self.fascistPoliciesPassed) + " fascist policies have been passed.")
            if(self.fascistPoliciesPassed == 5):
                await self.sendMessage("Veto power has been unlocked")
            if(self.playerCount <= 6):
                if(self.fascistPoliciesPassed < 3):
                    await self.passPlacard()
                elif(self.fascistPoliciesPassed == 3):
                    await self.presidentDeckInvestigation()
                elif(self.fascistPoliciesPassed < 6):
                    await self.presidentShoot()
                else:
                    await self.sendMessage("Fascists have won the game!")
            elif(self.playerCount <= 8):
                if(self.fascistPoliciesPassed == 1):
                    await self.passPlacard()
                elif(self.fascistPoliciesPassed == 2):
                    await self.presidentPlayerInvestigation()
                elif(self.fascistPoliciesPassed == 3):
                    await self.presidentChooseNextPresident()
                elif(self.fascistPoliciesPassed < 6):
                    await self.presidentShoot()
                else:
                    await self.sendMessage("Fascists have won the game!")
            else:
                if(self.fascistPoliciesPassed < 3):
                    await self.presidentPlayerInvestigation()
                elif(self.fascistPoliciesPassed == 3):
                    await self.presidentChooseNextPresident()
                elif(self.fascistPoliciesPassed < 6):
                    await self.presidentShoot()
                else:
                    await self.sendMessage("Fascists have won the game!")
                
    async def cardPhaseChancellor(self, amountFascist, amountLiberal, canVeto):
        choices = []
        if(amountFascist > 0):
            choices.append("fascist")
        if(amountLiberal > 0):
            choices.append("liberal")
        if(canVeto):
            choices.append("veto")
        ptext = "You were given " + str(amountFascist) + " fascist agendas and " + str(amountLiberal) + " liberal agendas. What would you like to discard?"
        await self.sendPromptTo(self.chancellor, ChoosePrompt(self, [], ptext, choices, self.playPolicyPhase))
    async def cardDiscardPhasePresident(self, voter, voted):
        if(voted == "fascist"):
            self.currentHandFascists = self.currentHandFascists - 1
            self.discard = self.discard + [self.fascistRole]
        else:
            self.discard = self.discard + [self.liberalRole]
        amountFascist = self.currentHandFascists
        amountLiberal = 2 - amountFascist
        await self.cardPhaseChancellor(amountFascist, amountLiberal, self.fascistPoliciesPassed == 5)
    async def cardPhasePresident(self):
        if(len(self.deck) < 3):
            await self.refillDeck()
        choices = self.deck[:3]
        self.deck = self.deck[3:]
        amountFascist = sum(choices)
        self.currentHandFascists = amountFascist
        amountLiberal = 3 - amountFascist
        choices = []
        if(amountFascist > 0):
            choices.append("fascist")
        if(amountLiberal > 0):
            choices.append("liberal")
        ptext = "You drew " + str(amountFascist) + " fascist agendas and " + str(amountLiberal) + " liberal agendas. What would you like to discard?"
        await self.sendPromptTo(self.turnOrder[self.placardPosition], ChoosePrompt(self, [], ptext, choices, self.cardDiscardPhasePresident))
    async def acceptNominationYN(self, voter, voted):
        print("Dealing with YN Nomination")
        if(voted == "yes"):
            self.yesAmount = self.yesAmount + 1
            self.yesNames = self.yesNames + [voter]
        else:
            self.noNames = self.noNames + [voter]
        random.shuffle(self.yesNames)
        random.shuffle(self.noNames)
    async def finishNomination(self):
        yesVotes = self.yesAmount
        noVotes = len(self.turnOrder) - yesVotes
        voteData = "Yes: " + (", ".join(self.yesNames)) + "\nNo: " + (", ".join(self.noNames))
        if(self.yesAmount > (len(self.turnOrder) // 2)):
            #vote passes
            self.lastPresident = self.turnOrder[self.placardPosition]
            self.lastChancellor = self.chancellor
            await self.sendMessage("Vote passed! There were " + str(yesVotes) + " votes for yes and " + str(noVotes) + " votes for no.\n" + voteData)
            if(self.fascistPoliciesPassed >= 3):
                if(self.hitlerRole in self.roles[self.chancellor]):
                    await self.sendMessage("You have elected the secret hitler " + self.chancellor.name + " as chancellor, fascists win!")
                    return
                else:
                    await self.sendMessage(self.chancellor.name + " is not the secret hitler.")
            await self.cardPhasePresident()
        else:
            #vote fails
            self.voteTracker = self.voteTracker + 1
            await self.sendMessage("Vote failed! There were " + str(yesVotes) + " votes for yes and " + str(noVotes) + " votes for no.\n" + voteData)
            await self.sendMessage("VOTE FAILED")
            if self.voteTracker == 3:
                self.lastPresident = None
                self.lastChancellor = None
                self.voteTracker = 0
                if(len(self.deck) < 1):
                    await self.refillDeck()
                chosen = self.deck[0]
                self.deck = self.deck[1:]
                await self.sendMessage("The populace is angry and riot to play an agenda of their own")
                if(chosen == self.fascistRole):
                    self.fascistPoliciesPassed = self.fascistPoliciesPassed + 1
                    await self.sendMessage("A fascist policy has been played")
                    await self.sendMessage("So far " + str(self.liberalPoliciesPassed) + " liberal policies have been passed and " + str(self.fascistPoliciesPassed) + " fascist policies have been passed.")
                    if(self.fascistPoliciesPassed == 6):
                        await self.sendMessage("Fascists have won the game!")
                    else:
                        await self.passPlacard()
                else:
                    self.liberalPoliciesPassed = self.liberalPoliciesPassed + 1
                    await self.sendMessage("A liberal policy has been played")
                    await self.sendMessage("So far " + str(self.liberalPoliciesPassed) + " liberal policies have been passed and " + str(self.fascistPoliciesPassed) + " fascist policies have been passed.")
                    if(self.liberalPoliciesPassed == 5):
                        self.sendMessage("Liberals have won the game!")
            else:
                await self.sendMessage("Vote tracker is at " + str(self.voteTracker))
                await self.passPlacard()
                
    async def votePhase(self, voter, voted):
        self.chancellor = self.getMemberFromName(voted)
        await self.sendMessage(self.chancellor.name + " was nominated for Chancellor!")
        self.yesAmount = 0
        self.yesNames = []
        self.noNames = []
        await self.sendPromptToAllWithRole(self.aliveRole, YNPrompt(self, "Do you accept the nomination of " + self.chancellor.name + " for chancellor?", self.acceptNominationYN), self.finishNomination)
    async def nominateChancellor(self):
        await self.sendPromptTo(self.turnOrder[self.placardPosition], ChooseMemberInRolePrompt(self, self.aliveRole, self.getNonChancellorable(), "Who would you like to nominate as chancellor?", self.votePhase))
    async def passPlacard(self):
        self.placardPosition = (self.placardPosition + 1) % len(self.turnOrder)
        await self.nominateChancellor()
    async def endGame(self):
        pass

class OneNightWerewolfGame(Game):
    villagerRole = 0
    werewolfRole = 1
    minionRole = 2
    seerRole = 3
    robberRole = 4
    troubleMakerRole = 5
    def getRoleName(self, role):
        if(role == self.villagerRole):
            return "Villager"
        elif(role == self.werewolfRole):
            return "Werewolf"
        elif(role == self.minionRole):
            return "Minion"
        elif(role == self.seerRole):
            return "Seer"
        elif(role == self.robberRole):
            return "Robber"
        elif(role == self.troubleMakerRole):
            return "Troublemaker"
        return "Unknown"
    def getPlayerIndex(self, name):
        ind = 0
        for p in self.players:
            if p.name == name:
                return ind
            ind = ind + 1
        return -1
    def getMiddleIndex(self, pos):
        if pos.lower() == "left":
            return -3
        elif pos.lower() == "middle":
            return -2
        return -1
    async def printDeck(self):
        data = "--PLAYER CARDS--\n"
        data = data + ("\n".join([(self.players[i].name + ": " + self.getRoleName(self.deck[i])) for i in range(len(self.players))]))
        data = data + "\n--MIDDLE CARDS--\n"
        data = data + "Left: " + self.getRoleName(self.deck[-3]) + "\n"
        data = data + "Middle: " + self.getRoleName(self.deck[-2]) + "\n"
        data = data + "Right: " + self.getRoleName(self.deck[-1])
        await self.sendMessage(data)
    async def seerPlayerCallback(self, voter, voted):
        self.seerActionType = 'P'
        self.seerAction1 = voted
    async def seerMiddleCallback(self, voter, voted):
        seer = self.getMemberFromName(voter)
        self.seerActionType = 'M'
        self.seerAction1 = voted
        await self.sendPromptParasiteTo(seer, ChoosePrompt(self, [self.seerAction1], "Which middle card would you like to see second?", ["Left", "Middle", "Right"], self.seerMiddleSecondCallback))
    async def seerMiddleSecondCallback(self, voter, voted):
        self.seerAction2 = voted
    async def seerCallback(self, voter, voted):
        seer = self.getMemberFromName(voter)
        self.seer = seer
        if(voted == "player"):
            await self.sendPromptParasiteTo(seer, ChooseMemberPrompt(self, [voter], "Whose card would you like to see?", self.seerPlayerCallback))
        elif(voted == "middle"):
            await self.sendPromptParasiteTo(seer, ChoosePrompt(self, [], "Which middle card would you like to see first?", ["Left", "Middle", "Right"], self.seerMiddleCallback))
        else:
            pass
    async def robberCallback(self, voter, voted):
        robber = self.getMemberFromName(voter)
        self.robber = robber
        if(voted == "steal"):
            await self.sendPromptParasiteTo(robber, ChooseMemberPrompt(self, [voter], "Whose card would you like to steal?", self.robberSecondCallback))
        else:
            pass
    async def robberSecondCallback(self, voter, voted):
        self.robberAction = voted
    async def troubleCallback(self, voter, voted):
        troubleMaker = self.getMemberFromName(voter)
        self.troubleMaker = troubleMaker
        if(voted == "swap"):
            await self.sendPromptParasiteTo(troubleMaker, ChooseMemberPrompt(self, [voter], "Whose card would you like to swap first?", self.troubleSecondCallback))
        else:
            pass
    async def troubleSecondCallback(self, voter, voted):
        troubleMaker = self.getMemberFromName(voter)
        self.troubleMakerAction1 = voted
        await self.sendPromptParasiteTo(troubleMaker, ChooseMemberPrompt(self, [voter, voted], "Whose card would you like to swap it with?", self.troubleThirdCallback))
    async def troubleThirdCallback(self, voter, voted):
        troubleMaker = self.getMemberFromName(voter)
        self.troubleMakerAction2 = voted
    async def nightPhase(self):
        pb = PromptsBarrier(self, self.nightPhaseFinish)
        for m in self.members:
            if self.villagerRole in self.roles[m]:
                p = ChoosePrompt(self, [], "You are a villager, what would you like to do during the night phase?", ["Nothing"], doNothingCallbackWithArgs)
                p.setMember(m)
                pb.addPrompt(p)
            if self.werewolfRole in self.roles[m]:
                ww = self.getMemberNamesInRole(self.werewolfRole)
                await self.sendMessageToRole(self.werewolfRole, "--WEREWOLVES--\n" + ("\n".join(ww)))
                p = ChoosePrompt(self, [], "You are a werewolf, what would you like to do during the night phase?", ["Nothing"], doNothingCallbackWithArgs)
                p.setMember(m)
                pb.addPrompt(p)
            if self.minionRole in self.roles[m]:
                await self.sendMessageToRole(self.minionRole, "--WEREWOLVES--\n" + ("\n".join(self.getMemberNamesInRole(self.werewolfRole))))
                p = ChoosePrompt(self, [], "You are the minion, what would you like to do during the night phase?", ["Nothing"], doNothingCallbackWithArgs)
                p.setMember(m)
                pb.addPrompt(p)
            if self.seerRole in self.roles[m]:
                p = ChoosePrompt(self, [], "You are the seer, would you like to look at a player card, look at two middle cards, or do nothing?", ["Player", "Middle", "Nothing"], self.seerCallback)
                p.setMember(m)
                pb.addPrompt(p)
            if self.robberRole in self.roles[m]:
                p = ChoosePrompt(self, [], "You are the robber, would you like to steal a card or do nothing?", ["Steal", "Nothing"], self.robberCallback)
                p.setMember(m)
                pb.addPrompt(p)
            if self.troubleMakerRole in self.roles[m]:
                p = ChoosePrompt(self, [], "You are the troublemaker, would you like to swap cards or do nothing?", ["Swap", "Nothing"], self.troubleCallback)
                p.setMember(m)
                pb.addPrompt(p)
        self.promptBarrier = pb
        await pb.triggerPrompts()
    async def nightPhaseFinish(self):
        seerData = "--SEER--\n" + str([self.seerActionType, self.seerAction1, self.seerAction2])
        robberData = "--ROBBER--\n" + str([self.robberAction])
        troubleMakerData = "--TROUBLEMAKER--\n" + str([self.troubleMakerAction1, self.troubleMakerAction2])
        #await self.printDeck()
        if(self.seerActionType is not None):
            if(self.seerActionType == 'P'):
                pindex = self.getPlayerIndex(self.seerAction1)
                cardData = self.getRoleName(self.deck[pindex])
                await self.sendDM(self.seer, self.players[pindex].name + " had the " + cardData + " role!")
            else:
                index1 = self.getMiddleIndex(self.seerAction1)
                index2 = self.getMiddleIndex(self.seerAction2)
                cardData1 = self.getRoleName(self.deck[index1])
                cardData2 = self.getRoleName(self.deck[index2])
                await self.sendDM(self.seer, self.seerAction1 + " had the " + cardData1 + " role and " + self.seerAction2 + " had the " + cardData2 + " role!")
        #await self.printDeck()
        if(self.robberAction is not None):
            robbedIndex = self.getPlayerIndex(self.robberAction)
            robberIndex = self.getPlayerIndex(self.robber.name)
            temp = self.deck[robbedIndex]
            self.deck[robbedIndex] = self.deck[robberIndex]
            self.deck[robberIndex] = temp
            await self.sendDM(self.robber, "You robbed the " + self.getRoleName(self.deck[robberIndex]) + " role from " + self.players[robbedIndex].name + "!")
        #await self.printDeck()
        if(self.troubleMakerAction1 is not None):
            tindex1 = self.getPlayerIndex(self.troubleMakerAction1)
            tindex2 = self.getPlayerIndex(self.troubleMakerAction2)
            temp = self.deck[tindex1]
            self.deck[tindex1] = self.deck[tindex2]
            self.deck[tindex2] = temp
            await self.sendDM(self.troubleMaker, "You swapped cards between " + self.players[tindex1].name + " and " + self.players[tindex2].name + "!")
        await self.sendMessage("The Night Phase has been finished")
        #await self.printDeck()
    async def startGame(self, channel):
        self.roles = dict()
        self.fakerVotes = dict()
        self.setChannel(channel)
        self.players = list(self.members)
        cardsNeeded = len(self.members) + 3
        self.seer = None
        self.seerActionType = None
        self.seerAction1 = None
        self.seerAction2 = None
        self.robber = None
        self.robberAction = None
        self.troubleMaker = None
        self.troubleMakerAction1 = None
        self.troubleMakerAction2 = None
        self.deck = ([self.werewolfRole] * 2) + [self.seerRole, self.robberRole, self.troubleMakerRole, self.villagerRole]
        if(cardsNeeded >= 7):
            self.deck = self.deck + [self.villagerRole]
        if(cardsNeeded >= 8):
            self.deck = self.deck + [self.villagerRole]
        random.shuffle(self.deck)
        self.middleCards = [self.deck[-3], self.deck[-2], self.deck[-1]]
        for i in range(len(self.players)):
            self.roles[self.players[i]] = [self.deck[i]]
        await self.nightPhase()
    async def vote(self, whoVoted, votedFor):
        if votedFor in self.fakerVotes:
            self.fakerVotes[votedFor] = self.fakerVotes[votedFor] + 1
        else:
            self.fakerVotes[votedFor] = 1
    async def printOutResults(self):
        votes = []
        for key in self.fakerVotes:
            votes.append(key + " has " + str(self.fakerVotes[key]) + " votes!")
        await self.sendMessage("\n".join(votes))
        await self.printDeck()
    async def endGame(self):
        self.gamePhase = 2
        q = f'Please vote for one of the following: ' + ", ".join(self.getMemberNames()) + " by replying with the name"
        await self.sendPromptToAll(ChooseMemberPrompt(self, [], q, self.vote), self.printOutResults)

games = [OneNightWerewolfGame("one-night-werewolf"), FakeArtistGame("fake-artist"), SecretHitlerGame("secret-hitler")]

topics = []

with open('words.csv', newline='') as csvfile:
    spamreader = csv.reader(csvfile, delimiter=',', quotechar='|')
    for row in spamreader:
        topics.append((row[0], row[1]))
print(topics)

@bot.command()
async def foo(ctx):
    print("BOO")
    await ctx.send(":D")

@client.event
async def on_ready():
    guild = client.guilds[0]
    members = '\n - '.join([member.name for member in guild.members])
    print(f'Guild Members:\n - {members}')
    print(f'{client.user} has connected to Discord!')

async def lock():
    while not (await lockHandler()):
        pass
async def lockHandler():
    global spinLock
    if spinLock == 1:
        await asyncio.sleep(0)
        return False
    else:
        spinLock = 1
        print("ACQUIRED LOCK")
        return True
def unlock():
    global spinLock
    print("RELEASED LOCK")
    spinLock = 0

@client.event
async def on_message(message):
    global games
    if message.author != client.user:
        if isinstance(message.channel, discord.DMChannel):
            await lock()
            await handle_direct_message(message.author, message.content)
            unlock()
        else:
            words = message.content.split()
            if(words[0] == "fakesay"):
                await tlock()
                await handle_general_message(getFakePlayer(words[1], message.channel), " ".join(words[2:]), message.channel)
                unlock()
            elif(words[0] == "fakedm"):
                await lock()
                await handle_direct_message(getFakePlayer(words[1], message.channel), " ".join(words[2:]))
                unlock()
            elif(words[0] == "quicksetup"):
                for i in range(int(words[1])):
                     pname = "p" + str(i + 1)
                     await lock()
                     await handle_general_message(getFakePlayer(pname, message.channel), "join", message.channel)
                     unlock()
            elif(words[0] == "quickdm"):
                for i in range(int(words[1])):
                     pname = "p" + str(i + 1)
                     await lock()
                     await handle_direct_message(getFakePlayer(pname, message.channel), " ".join(words[2:]))
                     unlock()
            else:
                await lock()
                await handle_general_message(message.author, message.content, message.channel)
                unlock()

async def handle_direct_message(player, message):
    for g in games:
        if g.promptBarrier != None:
            for p in g.promptBarrier.prompts:
                if(p.member == player and not p.answered):
                    await p.answer(message.lower())
                    break
        else:
            if g.channel is not None and player in g.members:
                await handle_general_message(player, message, g.channel)

async def handle_general_message(player, message, channel):
    global games
    message = message.lower()
    if(channel.name == "uwu"):
        await channel.send("uwu")
    for g in games:
        if(channel.name == g.channel_name):
            if message == "join":
                g.addMember(player)
                await g.sendQueue(channel)
            if message == "leave" or message == "leaf":
                g.removeMember(player)
                await g.sendQueue(channel)
            if message == "start":
                await g.startGame(channel)
            if message == "end":
                await g.endGame()

client.run(TOKEN)
