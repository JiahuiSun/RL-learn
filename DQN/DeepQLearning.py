# coding: utf-8
import tensorflow as tf
import numpy as np
from collections import deque
import random


class DeepQLearning:
    def __init__(  # 缺乏对神经网络的定义，比如hiddenlayer大小，可以用**kwargs
        self,
        action_dim,                 # action number
        state_dim,                  # state number
        gamma=0.9,                  # discounted rate
        epsilon=0.5,                # explore rate
        hidden_nodes_size=30,       # hidden layer nodes number
        replay_buffer_size=10000,   # max buffer size
        replace_target_freq=5,      # fix Q-target update steps
        # checkpoint_steps = 100,     # save model and weights
        learning_rate=0.01,         # learning rate of DNN
        batch_size=32,              # batch size
        epsilon_decrement=None,     # explore decrease
        output_graph=False,         # whether output tensorflow graph
        save_path='./model.ckpt'
    ):
        self.action_dim = action_dim
        self.state_dim = state_dim
        self.gamma = gamma 
        self.epsilon = epsilon 
        self.hidden_nodes_size = hidden_nodes_size
        self.replay_buffer = deque()
        self.replay_buffer_size = replay_buffer_size
        self.replace_target_freq = replace_target_freq
        self.learning_rate = learning_rate
        self.batch_size = batch_size 
        self.epsilon_decrement = epsilon_decrement

        self.learn_step_counter = 0
        self.save_path = save_path
        # self.checkpoint_steps = checkpoint_steps
        # 创建网络[target_net and evaluate_net]
        self._build_Q_network()

        # 创建会话
        self.sess = tf.Session()
        if output_graph:
            tf.summary.FileWriter("logs/", self.sess.graph)

        # tf参数初始化
        self.sess.run(tf.global_variables_initializer())
        self.saver = tf.train.Saver()
        # 保存cost的历史
        self.cost_history = []


    def _build_Q_network(self):
        # define all inputs 
        self.s = tf.placeholder(tf.float32, [None, self.state_dim], name='s')
        self.s_ = tf.placeholder(tf.float32, [None, self.state_dim], name='s_')
        self.a = tf.placeholder(tf.int32, [None, ], name='a')
        self.r = tf.placeholder(tf.float32, [None, ], name='r')
        self.done = tf.placeholder(tf.float32, [None, ], name='done')

        w_initializer, b_initializer = tf.random_normal_initializer(0., 0.3), tf.constant_initializer(0.1)

        # build evaluate network
        with tf.variable_scope('eval_net'):
            eval_1 = tf.layers.dense(self.s, self.hidden_nodes_size, activation=tf.nn.relu, kernel_initializer=w_initializer, 
                                    bias_initializer=b_initializer, name='eval_1')
            self.q_eval = tf.layers.dense(eval_1, self.action_dim, kernel_initializer=w_initializer, 
                                    bias_initializer=b_initializer, name='q_eval')
            
        # build target network
        with tf.variable_scope('targ_net'):
            targ_1 = tf.layers.dense(self.s_, self.hidden_nodes_size, activation=tf.nn.relu, kernel_initializer=w_initializer, 
                                    bias_initializer=b_initializer, name='targ_1')
            self.q_next = tf.layers.dense(targ_1, self.action_dim, kernel_initializer=w_initializer,
                                    bias_initializer=b_initializer, name='q_next')

        # target网络，对q_直接取max即可, y + maxQ(s', a')
        with tf.variable_scope('q_target'): 
            q_target = self.r + self.gamma * (1 - self.done) * tf.reduce_max(self.q_next, axis=1, name='maxQs_a_')
            self.q_target = tf.stop_gradient(q_target)
        # evaluate网络，对q要取对应的q(s, a)
        with tf.variable_scope('q_eval'):
            # 就是得到随机的action的Q(s, a)
            a_indices = tf.stack([tf.range(tf.shape(self.a)[0], dtype=tf.int32), self.a], axis=1)
            self.q_eval_wrt_a = tf.gather_nd(params=self.q_eval, indices=a_indices)
        # loss function and optimizer
        with tf.variable_scope('loss'):
            self.loss = tf.reduce_mean(tf.squared_difference(self.q_target, self.q_eval_wrt_a, name='TD_error'))
        with tf.variable_scope('train'):
            self.train = tf.train.RMSPropOptimizer(self.learning_rate).minimize(self.loss)
    
        # 定义网络复制操作
        eval_params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='eval_net')
        targ_params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='targ_net')
        self.target_replace_op = [tf.assign(t, e) for t, e in zip(targ_params, eval_params)]

    
    # 训练网络
    def train_Q_network(self):
        # 如果到达步数就更新参数
        if self.learn_step_counter % self.replace_target_freq == 0:
            self.sess.run(self.target_replace_op)
            print('target parameters replaced at step {}'.format(self.learn_step_counter))

        # # 如果到达步数就保存模型
        # if self.learn_step_counter % self.checkpoint_steps == 0:
        #     save_path = self.saver.save(self.sess, "./tmp/model.ckpt", global_step=self.learn_step_counter)
        #     print("Model saved in path: %s" % save_path)
        
        # sample (s, a, r, s') 如果开始没有足够的数据怎么办？？？
        try:
            batch = random.sample(self.replay_buffer, self.batch_size)
            state_batch = [data[0] for data in batch]
            action_batch = [data[1] for data in batch]
            reward_batch = [data[2] for data in batch]
            next_state_batch = [data[3] for data in batch]
            done = [data[4] for data in batch]
        except:
            print('no enough buffer history')
            return 

        # 开始训练
        _, cost = self.sess.run(
            [self.train, self.loss],
            feed_dict={
                self.s: state_batch,
                self.a: action_batch,
                self.r: reward_batch, 
                self.s_: next_state_batch,
                self.done: done,
            }
        )

        self.cost_history.append(cost)
        self.learn_step_counter += 1


    def save_transtion(self, state, action, reward, next_state, done):
        self.replay_buffer.append((state, action, reward, next_state, done))
        if len(self.replay_buffer) > self.replay_buffer_size:
            self.replay_buffer.popleft()

    
    def choose_action(self, observation, eval=False):
        # make it into batch form
        observation = observation[np.newaxis, :]
        # if np.random.uniform() < self.epsilon:
        #     action = random.randint(0, self.action_dim-1)
        # else:
        #     # forward feed the observation and get q value for every actions
        #     actions_value = self.sess.run(self.q_eval, feed_dict={self.s: observation})
        #     action = np.argmax(actions_value)

        # if self.epsilon_decrement is not None:
        #     self.epsilon -= self.epsilon_decrement

        # refactor
        if eval:
            actions_value = self.sess.run(self.q_eval, feed_dict={self.s: observation})
            return np.argmax(actions_value)
        if self.epsilon_decrement != None:
            self.epsilon -= self.epsilon_decrement
        action_probs = np.ones(self.action_dim) * self.epsilon / self.action_dim
        actions_value = self.sess.run(self.q_eval, feed_dict={self.s: observation})
        max_a = np.argmax(actions_value)
        action_probs[max_a] += 1 - self.epsilon
        action = np.random.choice(self.action_dim, p=action_probs)
        return action

    def eval_policy(self):
        # tf.reset_default_graph()
        self.saver.restore(self.sess, self.save_path)
