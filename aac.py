#
# aac.py, doom-net
#
# Created by Andrey Kolishchak on 01/21/17.
#
import torch.nn as nn
import torch.nn.functional as F
from cuda import *
from collections import namedtuple

ModelOutput = namedtuple('ModelOutput', ['action', 'value'])


class AdvantageActorCritic(nn.Module):

    def __init__(self, args):
        super(AdvantageActorCritic, self).__init__()
        self.discount = args.episode_discount
        feature_num = 64
        self.conv1 = nn.Conv2d(in_channels=args.screen_size[0], out_channels=32, kernel_size=3, stride=1)
        self.conv2 = nn.Conv2d(in_channels=32, out_channels=64, kernel_size=3, stride=1)
        self.conv3 = nn.Conv2d(in_channels=64, out_channels=64, kernel_size=3, stride=1)
        self.conv4 = nn.Conv2d(in_channels=64, out_channels=64, kernel_size=3, stride=2)

        self.features = nn.Linear(64 * 14 * 19, feature_num)
        self.batch_norm = nn.BatchNorm1d(feature_num)
        self.action = nn.Linear(feature_num, args.button_num)
        self.value = nn.Linear(feature_num, 1)
        self.outputs = []
        self.rewards = []

    def reset(self):
        self.outputs = []
        self.rewards = []

    def forward(self, input):
        # cnn
        input = F.relu(self.conv1(input))
        input = F.relu(F.max_pool2d(self.conv2(input), kernel_size=2, stride=2))
        input = F.relu(F.max_pool2d(self.conv3(input), kernel_size=2, stride=2))
        input = F.relu(F.max_pool2d(self.conv4(input), kernel_size=2, stride=2))
        input = input.view(input.size(0), -1)
        # shared features
        features = F.relu(self.batch_norm(self.features(input)))
        # action
        action = F.softmax(self.action(features))
        if self.training:
            action = action.multinomial()
        else:
            _, action = action.max(1)
            return action, None
        # value prediction - critic
        value = self.value(features)
        # save output for backpro
        self.outputs.append(ModelOutput(action, value))
        return action, value

    def get_action(self, state):
        input = Variable(state.screen, volatile=not self.training)
        action, _ = self.forward(input)
        return action.data

    def set_reward(self, reward):
        self.rewards.append(reward*0.01)

    def backward(self):
        #
        # calculate step returns in reverse order
        returns = []
        step_return = self.outputs[-1].value.data
        for reward in self.rewards[::-1]:
            step_return.mul_(self.discount).add_(reward.cuda() if USE_CUDA else reward)
            returns.insert(0, step_return.clone())
        #
        # calculate losses
        value_loss = 0
        for i in range(len(self.outputs)):
            self.outputs[i].action.reinforce(returns[i] - self.outputs[i].value.data)
            value_loss += F.smooth_l1_loss(self.outputs[i].value, Variable(returns[i]))
        #
        # backpro all variables at once
        variables = [value_loss] + [output.action for output in self.outputs]
        gradients = [torch.ones(1).cuda() if USE_CUDA else torch.ones(1)] + [None for _ in self.outputs]
        autograd.backward(variables, gradients)
        # reset state
        self.reset()

