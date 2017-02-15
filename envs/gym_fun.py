#!/usr/bin/env python
import numpy
import gym
import pygame
import os
from pygame.locals import *
from sys import exit
import random
import cv2
from termcolor import colored

position = 5, 325
os.environ['SDL_VIDEO_WINDOW_POS'] = str(position[0]) + "," + str(position[1])
pygame.init()
#screen = pygame.display.set_mode((640,480),pygame.NOFRAME)

NOOP = 0
FIRE = 1
UP = 2
RIGHT = 4
LEFT = 3
DOWN = 5
# ACTION_MEANING = {
#     0 : "NOOP",
#     1 : "FIRE",
#     2 : "UP",
#     3 : "RIGHT",
#     4 : "LEFT",
#     5 : "DOWN",
#     6 : "UPRIGHT",
#     7 : "UPLEFT",
#     8 : "DOWNRIGHT",
#     9 : "DOWNLEFT",
#     10 : "UPFIRE",
#     11 : "RIGHTFIRE",
#     12 : "LEFTFIRE",
#     13 : "DOWNFIRE",
#     14 : "UPRIGHTFIRE",
#     15 : "UPLEFTFIRE",
#     16 : "DOWNRIGHTFIRE",
#     17 : "DOWNLEFTFIRE",
# }

class GameState:
    def __init__(self, human_demo=False, frame_skip=4, game='pong'):
        self.game = game
        if self.game == 'pong':
            self._env = gym.make('PongDeterministic-v3')
            print colored("PongDeterministic-v3", "green")
        elif self.game == 'breakout':
            self._env = gym.make('BreakoutDeterministic-v3')
            print colored("BreakoutDeterministic-v3", "green")
        self._env.frameskip = frame_skip
        self.lives = self._env.ale.lives()
        print colored("lives: {}".format(self.lives), "green")
        print colored("frameskip: {}".format(self._env.frameskip), "green")
        print colored("repeat_action_probability: {}".format(self._env.ale.getFloat('repeat_action_probability')), "green")

        self._human_demo = human_demo
        if self._human_demo:
            self._screen = pygame.display.set_mode((240,320),0,32)
        self.reinit()

    def reinit(self, gui=False, random_restart=False, is_testing=False):
        self.lost_life = False
        self.is_testing = is_testing
        if gui:
            self._env.render(mode='human')
        self._env.reset()
        self.lives = self._env.ale.lives()

        if random_restart:
            random_actions = random.randint(0, 30+1)
            for _ in range(random_actions):
                self.frame_step(0)
        self.frame_step(0)
        self.frame_step(0)

    def handle_user_event(self):
        pygame.event.get()

        keys = pygame.key.get_pressed()
        if keys[pygame.K_KP8] or keys[pygame.K_UP]:
            action_index = 1
        elif keys[pygame.K_KP2] or keys[pygame.K_DOWN]:
            action_index = 2
        elif keys[pygame.K_KP4] or keys[pygame.K_LEFT]:
            action_index = 1
        elif keys[pygame.K_KP6] or keys[pygame.K_RIGHT]:
            action_index = 2
        elif keys[pygame.K_KP5]:
            action_index = 3
        else:
            action_index = 0

        return action_index

    def frame_step(self, act, gui=False, random_restart=False):
        if self.game == 'pong':
            if act == 1:#Key up
                action = UP
            elif act == 2:#Key down
                action = DOWN
            else: # don't move
                action = 0
        elif self.game == 'breakout':
            if act == 1:#Key left
                action = LEFT
            elif act == 2:#Key right
                action = RIGHT
            elif act == 3: #FIRE
                action = FIRE
            else: # don't move
                action = 0
            if self._human_demo and self.lost_life:
                action = FIRE # fire automatically just during HUMAN DEMO
                self.lost_life = False

        observation, reward, terminal, info = self._env.step(action)

        if (self.lives - info['ale.lives']) != 0:
            self.lost_life = True
            self.lives -= 1
            # Consider terminal state after LOSS OF LIFE not after episode ends
            if not self.is_testing:
                terminal = True

        if self._human_demo:
            surface = pygame.surfarray.make_surface(observation)
            surface = pygame.transform.flip(surface, False, True)
            surface = pygame.transform.rotate(surface, -90)
            surface = pygame.transform.scale(surface, (240,320))
            bv = self._screen.blit(surface, (0,0))
            pygame.display.flip()
        if gui:
            self._env.render(mode='human')

        # cv2.imshow("observation", observation[33:195,:])
        # cv2.waitKey(2)

        if terminal:
            self.reinit(random_restart=random_restart)

        return observation[33:195,:], reward, (1 if terminal else 0)

# test_game = GameState()
# terminal = False
# while not terminal:
#     test_game.frame_step(random.choice([0,1,2]))
#     import time
#     time.sleep(2)