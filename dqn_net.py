#!/usr/bin/env python
import tensorflow as tf
import random
import numpy as np
from time import sleep
from util import plot_conv_weights, graves_rmsprop_optimizer
from termcolor import colored
from net import Network

try:
    import cPickle as pickle
except ImportError:
    import pickle


class DqnNet(Network):
    """ DQN Network Model of DQN Algorithm """

    def __init__(
        self, sess, height, width, phi_length, n_actions, name, gamma=0.99, copy_interval=4,
        optimizer='RMS', learning_rate=0.00025, epsilon=0.01, decay=0.95, momentum=0., l2_decay=0.0001, error_clip=1.0,
        slow=False, tau=0.01, verbose=False, path='', folder='_networks',
        transfer=False, transfer_folder='',
        transfer_conv2=False, transfer_conv3=False,
        transfer_fc1=False, transfer_fc2=False):
        """ Initialize network """
        Network.__init__(self, sess, name=name)
        self.gamma = gamma
        self.slow = slow
        self.tau = tau
        self.name = name
        self.sess = sess
        self.path = path
        self.folder = folder
        self.copy_interval = copy_interval
        self.update_counter = 0

        self.observation = tf.placeholder(tf.float32, [None, height, width, phi_length], name=self.name + '_observation')
        self.actions = tf.placeholder(tf.float32, shape=[None, n_actions], name=self.name + "_actions") # one-hot matrix
        self.next_observation = tf.placeholder(tf.float32, [None, height, width, phi_length], name=self.name + '_t_next_observation')
        self.rewards = tf.placeholder(tf.float32, shape=[None], name=self.name + "_rewards")
        self.terminals = tf.placeholder(tf.float32, shape=[None], name=self.name + "_terminals")

        self.slow_learnrate_vars = []
        self.fast_learnrate_vars = []

        self.observation_n = tf.div(self.observation, 255.)
        self.next_observation_n = tf.div(self.next_observation, 255.)

        # q network model:
        with tf.name_scope("Conv1") as scope:
            self.W_conv1, self.b_conv1 = self.conv_variable([8, 8, phi_length, 32], 'conv1')
            self.h_conv1 = tf.nn.relu(tf.add(self.conv2d(self.observation_n, self.W_conv1, 4), self.b_conv1), name=self.name + '_conv1_activations')
            tf.add_to_collection('conv_weights', self.W_conv1)
            tf.add_to_collection('conv_output', self.h_conv1)
            if transfer:
                self.slow_learnrate_vars.append(self.W_conv1)
                self.slow_learnrate_vars.append(self.b_conv1)

        with tf.name_scope("Conv2") as scope:
            self.W_conv2, self.b_conv2 = self.conv_variable([4, 4, 32, 64], 'conv2')
            self.h_conv2 = tf.nn.relu(tf.add(self.conv2d(self.h_conv1, self.W_conv2, 2), self.b_conv2), name=self.name + '_conv2_activations')
            tf.add_to_collection('conv_weights', self.W_conv2)
            tf.add_to_collection('conv_output', self.h_conv2)
            if transfer:
                self.slow_learnrate_vars.append(self.W_conv2)
                self.slow_learnrate_vars.append(self.b_conv2)

        with tf.name_scope("Conv3") as scope:
            self.W_conv3, self.b_conv3 = self.conv_variable([3, 3, 64, 64], 'conv3')
            self.h_conv3 = tf.nn.relu(tf.add(self.conv2d(self.h_conv2, self.W_conv3, 1), self.b_conv3), name=self.name + '_conv3_activations')
            tf.add_to_collection('conv_weights', self.W_conv3)
            tf.add_to_collection('conv_output', self.h_conv3)
            if transfer:
                self.slow_learnrate_vars.append(self.W_conv3)
                self.slow_learnrate_vars.append(self.b_conv3)

        self.h_conv3_flat = tf.reshape(self.h_conv3, [-1, 3136])

        with tf.name_scope("FullyConnected1") as scope:
            self.W_fc1, self.b_fc1 = self.fc_variable([3136, 512], 'fc1')
            self.h_fc1 = tf.nn.relu(tf.add(tf.matmul(self.h_conv3_flat, self.W_fc1), self.b_fc1), name=self.name + '_fc1_activations')
            if transfer:
                self.fast_learnrate_vars.append(self.W_fc1)
                self.fast_learnrate_vars.append(self.b_fc1)

        with tf.name_scope("FullyConnected2") as scope:
            self.W_fc2, self.b_fc2 = self.fc_variable([512, n_actions], 'fc2')
            self.q_value = tf.add(tf.matmul(self.h_fc1, self.W_fc2), self.b_fc2, name=self.name + '_fc1_outputs')
            if transfer:
                self.fast_learnrate_vars.append(self.W_fc2)
                self.fast_learnrate_vars.append(self.b_fc2)

        if transfer:
            self.load_transfer_model(
                folder=transfer_folder,
                transfer_conv2=transfer_conv2, transfer_conv3=transfer_conv3,
                transfer_fc1=transfer_fc1, transfer_fc2=transfer_fc2)

            if transfer_fc2:
                # Scale down the last layer if it's transferred
                print (colored("Normalizing output layer with max value {}...".format(self.transfer_max_output_val), "yellow"))
                W_fc2_norm = tf.div(self.W_fc2, self.transfer_max_output_val)
                b_fc2_norm = tf.div(self.b_fc2, self.transfer_max_output_val)
                print (colored("Output layer normalized", "green"))
                sleep(3)
                self.sess.run([
                   self.W_fc2.assign(W_fc2_norm), self.b_fc2.assign(b_fc2_norm)
                ])

        if verbose:
            self.init_verbosity()

        # target q network model:
        with tf.name_scope("TConv1") as scope:
            kernel_shape = [8, 8, phi_length, 32]
            self.t_W_conv1, self.t_b_conv1 = self.conv_variable(kernel_shape, 't_conv1')
            self.t_h_conv1 = tf.nn.relu(tf.add(self.conv2d(self.next_observation_n, self.t_W_conv1, 4), self.t_b_conv1), name=self.name + '_t_conv1_activations')

        with tf.name_scope("TConv2") as scope:
            kernel_shape = [4, 4, 32, 64]
            self.t_W_conv2, self.t_b_conv2 = self.conv_variable(kernel_shape, 't_conv2')
            self.t_h_conv2 = tf.nn.relu(tf.add(self.conv2d(self.t_h_conv1, self.t_W_conv2, 2), self.t_b_conv2), name=self.name + '_t_conv2_activations')

        with tf.name_scope("TConv3") as scope:
            kernel_shape = [3, 3, 64, 64]
            self.t_W_conv3, self.t_b_conv3 = self.conv_variable(kernel_shape, 't_conv3')
            self.t_h_conv3 = tf.nn.relu(tf.add(self.conv2d(self.t_h_conv2, self.t_W_conv3, 1), self.t_b_conv3), name=self.name + '_t_conv3_activations')

        self.t_h_conv3_flat = tf.reshape(self.t_h_conv3, [-1, 3136])

        with tf.name_scope("TFullyConnected1") as scope:
            kernel_shape = [3136, 512]
            self.t_W_fc1, self.t_b_fc1 = self.fc_variable(kernel_shape, 't_fc1')
            self.t_h_fc1 = tf.nn.relu(tf.add(tf.matmul(self.t_h_conv3_flat, self.t_W_fc1), self.t_b_fc1), name=self.name + '_t_fc1_activations')

        with tf.name_scope("TFullyConnected2") as scope:
            kernel_shape = [512, n_actions]
            self.t_W_fc2, self.t_b_fc2 = self.fc_variable(kernel_shape, 't_fc2')
            self.t_q_value = tf.add(tf.matmul(self.t_h_fc1, self.t_W_fc2), self.t_b_fc2, name=self.name + '_t_fc1_outputs')

        if transfer:
            # only intialize tensor variables that are not loaded from the transfer model
            self._global_vars_temp = set(tf.global_variables())

        # cost of q network
        self.cost = self.build_loss(error_clip, n_actions) #+ self.l2_regularizer_loss
        # self.parameters = [
        #     self.W_conv1, self.b_conv1,
        #     self.W_conv2, self.b_conv2,
        #     self.W_conv3, self.b_conv3,
        #     self.W_fc1, self.b_fc1,
        #     self.W_fc2, self.b_fc2,
        # ]
        with tf.name_scope("Train") as scope:
            if optimizer == "Graves":
                # Nature RMSOptimizer
                self.train_step, self.grads_vars = graves_rmsprop_optimizer(self.cost, learning_rate, decay, epsilon, 1)
            else:
                if optimizer == "Adam":
                    self.opt = tf.train.AdamOptimizer(learning_rate=learning_rate, epsilon=epsilon)
                elif optimizer == "RMS":
                    # Tensorflow RMSOptimizer
                    self.opt = tf.train.RMSPropOptimizer(learning_rate, decay=decay, momentum=momentum, epsilon=epsilon)
                else:
                    print (colored("Unknown Optimizer!", "red"))
                    sys.exit()

                self.grads_vars = self.opt.compute_gradients(self.cost)
                grads = []
                params = []
                for p in self.grads_vars:
                    if p[0] == None:
                        continue
                    grads.append(p[0])
                    params.append(p[1])
                #grads = tf.clip_by_global_norm(grads, 1)[0]
                self.grads_vars_updates = zip(grads, params)
                self.train_step = self.opt.apply_gradients(self.grads_vars_updates)

            # for grad, var in self.grads_vars:
            #     if grad == None:
            #         continue
            #     tf.summary.histogram(var.op.name + '/gradients', grad)

        if transfer:
            vars_diff = set(tf.global_variables()) - self._global_vars_temp
            self.sess.run(tf.variables_initializer(vars_diff))
        else:
            # initialize all tensor variable parameters
            self.sess.run(tf.global_variables_initializer())

        # Make sure q and target model have same initial parameters copy the parameters
        self.sess.run([
            self.t_W_conv1.assign(self.W_conv1), self.t_b_conv1.assign(self.b_conv1),
            self.t_W_conv2.assign(self.W_conv2), self.t_b_conv2.assign(self.b_conv2),
            self.t_W_conv3.assign(self.W_conv3), self.t_b_conv3.assign(self.b_conv3),
            self.t_W_fc1.assign(self.W_fc1), self.t_b_fc1.assign(self.b_fc1),
            self.t_W_fc2.assign(self.W_fc2), self.t_b_fc2.assign(self.b_fc2)
        ])

        if self.slow:
            self.update_target_op = [
                self.t_W_conv1.assign(self.tau*self.W_conv1 + (1-self.tau)*self.t_W_conv1),
                self.t_b_conv1.assign(self.tau*self.b_conv1 + (1-self.tau)*self.t_b_conv1),
                self.t_W_conv2.assign(self.tau*self.W_conv2 + (1-self.tau)*self.t_W_conv2),
                self.t_b_conv2.assign(self.tau*self.b_conv2 + (1-self.tau)*self.t_b_conv2),
                self.t_W_conv3.assign(self.tau*self.W_conv3 + (1-self.tau)*self.t_W_conv3),
                self.t_b_conv3.assign(self.tau*self.b_conv3 + (1-self.tau)*self.t_b_conv3),
                self.t_W_fc1.assign(self.tau*self.W_fc1 + (1-self.tau)*self.t_W_fc1),
                self.t_b_fc1.assign(self.tau*self.b_fc1 + (1-self.tau)*self.t_b_fc1),
                self.t_W_fc2.assign(self.tau*self.W_fc2 + (1-self.tau)*self.t_W_fc2),
                self.t_b_fc2.assign(self.tau*self.b_fc2 + (1-self.tau)*self.t_b_fc2),
            ]
        else:
            self.update_target_op = [
                self.t_W_conv1.assign(self.W_conv1), self.t_b_conv1.assign(self.b_conv1),
                self.t_W_conv2.assign(self.W_conv2), self.t_b_conv2.assign(self.b_conv2),
                self.t_W_conv3.assign(self.W_conv3), self.t_b_conv3.assign(self.b_conv3),
                self.t_W_fc1.assign(self.W_fc1), self.t_b_fc1.assign(self.b_fc1),
                self.t_W_fc2.assign(self.W_fc2), self.t_b_fc2.assign(self.b_fc2),
            ]

        self.saver = tf.train.Saver()
        if self.folder is not None:
            self.merged = tf.summary.merge_all()
            self.writer = tf.summary.FileWriter(self.path + self.folder + '/log_tb', self.sess.graph)

    def evaluate(self, state):
        return self.sess.run(self.q_value, feed_dict={self.observation: state})

    def evaluate_target(self, state):
        return self.sess.run(self.t_q_value, feed_dict={self.next_observation: state})

    def build_loss(self, error_clip, n_actions):
        with tf.name_scope("Cost") as scope:
            predictions = tf.reduce_sum(tf.multiply(self.q_value, self.actions), axis=1)
            max_action_values = tf.reduce_max(self.t_q_value, 1)
            clipped_rewards = tf.clip_by_value(self.rewards, -1., 1.)
            targets = tf.stop_gradient(clipped_rewards + (self.gamma * max_action_values * (1 - self.terminals)))
            difference = tf.abs(targets - predictions)
            if error_clip >= 0:
                quadratic_part = tf.minimum(difference, error_clip)
                linear_part = difference - quadratic_part
                errors = (0.5 * tf.square(quadratic_part)) + (error_clip * linear_part)
            else:
                errors = (0.5 * tf.square(difference))
            cost = tf.reduce_sum(errors, name='loss')
            tf.summary.scalar("cost", cost)
            tf.summary.scalar("cost_0", errors[0])
            tf.summary.scalar("cost_max", tf.reduce_max(errors))
            tf.summary.scalar("target_0", targets[0])
            tf.summary.scalar("target_max", tf.reduce_max(targets))
            tf.summary.scalar("acted_Q_0", predictions[0])
            tf.summary.scalar("acted_Q_max", tf.reduce_max(predictions))
            tf.summary.scalar("reward_max", tf.reduce_max(clipped_rewards))
            return cost

    def train(self, s_j_batch, a_batch, r_batch, s_j1_batch, terminal):
        t_ops = [self.merged, self.train_step, self.cost]
        summary = self.sess.run(
            t_ops,
            feed_dict={
                self.observation: s_j_batch,
                self.actions: a_batch,
                self.next_observation: s_j1_batch,
                self.rewards: r_batch,
                self.terminals: terminal
            }
        )
        if self.update_counter % self.copy_interval == 0:
            if not self.slow:
                print (colored('Update target network', 'green'))
            self.update_target_network()
        self.update_counter += 1
        return summary[0]

    def add_accuracy(self, mean_reward, mean_length, n_episodes, step):
        summary = tf.Summary()
        summary.value.add(tag='Perf/Reward', simple_value=float(mean_reward))
        summary.value.add(tag='Perf/Length', simple_value=float(mean_length))
        summary.value.add(tag='Perf/Episodes', simple_value=float(n_episodes))
        self.writer.add_summary(summary, step)
        self.writer.flush()

    def add_summary(self, summary, step):
        self.writer.add_summary(summary, step)
        self.writer.flush()

    def update_target_network(self):
        self.sess.run(self.update_target_op)

    def load(self, folder=None):
        has_checkpoint = False

        __folder = self.folder
        # saving and loading networks
        if folder is not None:
            __folder = folder
        checkpoint = tf.train.get_checkpoint_state(__folder)

        if checkpoint and checkpoint.model_checkpoint_path:
            self.saver.restore(self.sess, checkpoint.model_checkpoint_path)
            print (colored('Successfully loaded:{}'.format(checkpoint.model_checkpoint_path), 'green'))
            sleep(.2)
            has_checkpoint = True
            data = pickle.load(open(__folder + '/' + self.name + '-net-variables.pkl', 'rb'))
            self.update_counter = data['update_counter']

        return has_checkpoint

    def save(self, step=-1):
        print (colored('Saving checkpoint...', 'blue'))
        if step < 0:
            self.saver.save(self.sess, self.folder + '/' + self.name + '-dqn')
        else:
            self.saver.save(self.sess, self.folder + '/' + self.name + '-dqn', global_step=step)
            data = {'update_counter': self.update_counter}
            pickle.dump(data, open(self.folder + '/' + self.name + '-net-variables.pkl', 'wb'), pickle.HIGHEST_PROTOCOL)
        print (colored('Successfully saved checkpoint!', 'green'))

        print (colored('Saving parameters as csv files...', 'blue'))
        W1_val = self.W_conv1.eval()
        np.savetxt(self.folder + '/conv1_weights.csv', W1_val.flatten())
        b1_val = self.b_conv1.eval()
        np.savetxt(self.folder + '/conv1_biases.csv', b1_val.flatten())

        W2_val = self.W_conv2.eval()
        np.savetxt(self.folder + '/conv2_weights.csv', W2_val.flatten())
        b2_val = self.b_conv2.eval()
        np.savetxt(self.folder + '/conv2_biases.csv', b2_val.flatten())

        W3_val = self.W_conv3.eval()
        np.savetxt(self.folder + '/conv3_weights.csv', W3_val.flatten())
        b3_val = self.b_conv3.eval()
        np.savetxt(self.folder + '/conv3_biases.csv', b3_val.flatten())

        Wfc1_val = self.W_fc1.eval()
        np.savetxt(self.folder + '/fc1_weights.csv', Wfc1_val.flatten())
        bfc1_val = self.b_fc1.eval()
        np.savetxt(self.folder + '/fc1_biases.csv', bfc1_val.flatten())

        Wfc2_val = self.W_fc2.eval()
        np.savetxt(self.folder + '/fc2_weights.csv', Wfc2_val.flatten())
        bfc2_val = self.b_fc2.eval()
        np.savetxt(self.folder + '/fc2_biases.csv', bfc2_val.flatten())
        print (colored('Successfully saved parameters!', 'green'))

        # print (colored('Saving convolutional weights as images...', 'blue'))
        # conv_weights = self.sess.run([tf.get_collection('conv_weights')])
        # for i, c in enumerate(conv_weights[0]):
        #     plot_conv_weights(c, 'conv{}'.format(i+1), folder=self.folder)
        # print (colored('Successfully saved convolutional weights!', 'green'))

    def init_verbosity(self):
        with tf.name_scope("Summary_Conv1") as scope:
            self.variable_summaries(self.W_conv1, 'weights')
            self.variable_summaries(self.b_conv1, 'biases')
            tf.summary.histogram('activations', self.h_conv1)
        with tf.name_scope("Summary_Conv2") as scope:
            self.variable_summaries(self.W_conv2, 'weights')
            self.variable_summaries(self.b_conv2, 'biases')
            tf.summary.histogram('activations', self.h_conv2)
        with tf.name_scope("Summary_Conv3") as scope:
            self.variable_summaries(self.W_conv3, 'weights')
            self.variable_summaries(self.b_conv3, 'biases')
            tf.summary.histogram('/activations', self.h_conv3)
        with tf.name_scope("Summary_Flatten") as scope:
            tf.summary.histogram('activations', self.h_conv3_flat)
        with tf.name_scope("Summary_FullyConnected1") as scope:
            self.variable_summaries(self.W_fc1, 'weights')
            self.variable_summaries(self.b_fc1, 'biases')
            tf.summary.histogram('activations', self.h_fc1)
        with tf.name_scope("Summary_FullyConnected2") as scope:
            self.variable_summaries(self.W_fc2, 'weights')
            self.variable_summaries(self.b_fc2, 'biases')
            tf.summary.histogram('activations', self.action_output)

    def load_transfer_model(self, folder='',
        transfer_conv2=True, transfer_conv3=True,
        transfer_fc1=True, transfer_fc2=True):
        assert folder != ''
        saver_transfer_from = tf.train.Saver()
        checkpoint_transfer_from = tf.train.get_checkpoint_state(folder)
        if checkpoint_transfer_from and checkpoint_transfer_from.model_checkpoint_path:
            saver_transfer_from.restore(self.sess, checkpoint_transfer_from.model_checkpoint_path)
            print (colored("Successfully loaded: {}".format(checkpoint_transfer_from.model_checkpoint_path), "green"))

        if transfer_fc2:
            with open(folder + "/max_output_value", 'r') as f_max_value:
                self.transfer_max_output_val = float(f_max_value.readline().split()[0])
            return

        # Overwrite layers that shouldn't be from transfer model
        # Assumption here is if a layer is not transferred,
        # then all layers above it are not transferred
        vars_init = []
        if not transfer_fc2 or not transfer_fc1 or not transfer_conv3 or not transfer_conv2:
            vars_init.append(self.W_fc2)
            vars_init.append(self.b_fc2)
        if not transfer_fc1 or not transfer_conv3 or not transfer_conv2:
            vars_init.append(self.W_fc1)
            vars_init.append(self.b_fc1)
        if not transfer_conv3 or not transfer_conv2:
            vars_init.append(self.W_conv3)
            vars_init.append(self.b_conv3)
        if not transfer_conv2:
            vars_init.append(self.W_conv2)
            vars_init.append(self.b_conv2)
        temp_str = ''
        for tf_vars in vars_init:
            temp_str += '\n' + tf_vars.op.name
        print ("Overwriting following vars:" + temp_str)
        sleep(2)
        self.sess.run(tf.variables_initializer(vars_init))
