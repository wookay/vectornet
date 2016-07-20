# Copyright (c) 2016 Byungsoo Kim. All Rights Reserved.
# 
# Byungsoo Kim, ETH Zurich
# kimby@student.ethz.ch, http://byungsoo.me
# ==============================================================================

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from datetime import datetime
import os
import time

from six.moves import xrange  # pylint: disable=redefined-builtin
import numpy as np
import tensorflow as tf

import linenet_data
import linenet_model

# parameters
FLAGS = tf.app.flags.FLAGS
tf.app.flags.DEFINE_string('log_dir', 'log',
                           """Directory where to write event logs """
                           """and checkpoint.""")
tf.app.flags.DEFINE_boolean('log_device_placement', False,
                            """Whether to log device placement.""")
tf.app.flags.DEFINE_string('pretrained_model_checkpoint_path', '', # 'log/second_train/linenet.ckpt',
                           """If specified, restore this pretrained model """
                           """before beginning any training.""")
tf.app.flags.DEFINE_integer('max_steps', 100000,
                            """Number of batches to run.""")
tf.app.flags.DEFINE_integer('decay_steps', 25000, 
                          """Decay steps""")
tf.app.flags.DEFINE_float('initial_learning_rate', 0.1,
                          """Initial learning rate.""")
tf.app.flags.DEFINE_float('learning_decay_factor', 0.1,
                          """Learning rate decay factor.""")
tf.app.flags.DEFINE_float('moving_avg_decay', 0.9999,
                          """The decay to use for the moving average.""")
tf.app.flags.DEFINE_float('clip_gradients', 0.1,
                          """range for clipping gradients.""")
tf.app.flags.DEFINE_integer('max_images', 1,
                            """max # images to save.""")
tf.app.flags.DEFINE_integer('stat_steps', 10,
                            """statistics steps.""")
tf.app.flags.DEFINE_integer('summary_steps', 100,
                            """summary steps.""")
tf.app.flags.DEFINE_integer('save_steps', 5000,
                            """save steps""")


def train():
    """Train the network for a number of steps."""
    with tf.Graph().as_default():
        global_step = tf.Variable(0, name='global_step', trainable=False)
        is_train = True
        phase_train = tf.placeholder(tf.bool, name='phase_train')
        
        # # debug
        # x_batch, y_batch = linenet_data.batch()

        # Get input and output image
        # use_data = False
        # if not use_data:            
        x = tf.placeholder(dtype=tf.float32, shape=[None, FLAGS.image_size, FLAGS.image_size, 1])
        y = tf.placeholder(dtype=tf.float32, shape=[None, FLAGS.image_size, FLAGS.image_size, 1])
            
        # Build a Graph that computes the logits predictions from the inference model.
        y_hat = linenet_model.inference(x, phase_train)

        # Calculate loss.
        loss = linenet_model.loss(y_hat, y)

        ###############################################################################
        # Build a Graph that trains the model with one batch of examples and
        # updates the model parameters.
        
        # Compute the moving average of all individual losses and the total loss.
        loss_averages = tf.train.ExponentialMovingAverage(0.9, name='avg')
        loss_averages_op = loss_averages.apply([loss])

        # Name each loss as '(raw)' and name the moving average version of the loss
        # as the original loss name.
        tf.scalar_summary(loss.op.name + ' (raw)', loss)
        tf.scalar_summary(loss.op.name, loss_averages.average(loss))
        
        # Decay the learning rate exponentially based on the number of steps.
        learning_rate = tf.train.exponential_decay(FLAGS.initial_learning_rate,
                                                   global_step,
                                                   FLAGS.decay_steps,
                                                   FLAGS.learning_decay_factor,
                                                   staircase=True)
        tf.scalar_summary('learning_rate', learning_rate)        
        # # or use fixed learning rate
        # learning_rate = 1e-3
        
        # Compute gradients.
        with tf.control_dependencies([loss_averages_op]):
            opt = tf.train.AdamOptimizer(learning_rate)            
            grads = opt.compute_gradients(loss)
            max_grad = FLAGS.clip_gradients / learning_rate
            clipped_grads = [(tf.clip_by_value(grad, -max_grad, max_grad), var) for grad, var in grads]

        apply_gradient_op = opt.apply_gradients(clipped_grads, global_step=global_step)

        # Add histograms for gradients.
        for grad, var in grads:
            if grad is not None:
                tf.histogram_summary(var.op.name + '/gradients', grad)

        # Track the moving averages of all trainable variables.
        variable_averages = tf.train.ExponentialMovingAverage(FLAGS.moving_avg_decay, global_step)
        variable_averages_op = variable_averages.apply(tf.trainable_variables())

        with tf.control_dependencies([apply_gradient_op, variable_averages_op]):
            train_op = tf.no_op(name='train')
        

        ####################################################################
        # Start running operations on the Graph. 
        sess = tf.Session(config=tf.ConfigProto(
            log_device_placement=FLAGS.log_device_placement))
        sess.run(tf.initialize_all_variables())

        # Create a saver (restorer).
        saver = tf.train.Saver()
        if FLAGS.pretrained_model_checkpoint_path:
            assert tf.gfile.Exists(FLAGS.pretrained_model_checkpoint_path)
            saver.restore(sess, FLAGS.pretrained_model_checkpoint_path)
            print('%s: Pre-trained model restored from %s' %
                (datetime.now(), FLAGS.pretrained_model_checkpoint_path))

        # Build the summary operation.
        summary_op = tf.merge_all_summaries()
        summary_writer = tf.train.SummaryWriter(FLAGS.log_dir, sess.graph)

        x_summary = tf.image_summary('x', x, max_images=FLAGS.max_images)
        y_summary = tf.image_summary('y', y, max_images=FLAGS.max_images)

        # # Start the queue runners.
        # tf.train.start_queue_runners(sess=sess)
        
        ####################################################################
        # Start to train.
        print('start to train')
        start_step = tf.train.global_step(sess, global_step)
        for step in xrange(start_step, FLAGS.max_steps):
            # Train one step.
            start_time = time.time()
            x_batch, y_batch = linenet_data.batch()
            _, loss_value = sess.run([train_op, loss], feed_dict={phase_train: is_train,
                                     x: x_batch, y: y_batch})
            duration = time.time() - start_time

            assert not np.isnan(loss_value), 'Model diverged with loss = NaN'

            # Print statistics periodically.
            if step % FLAGS.stat_steps == 0:
                examples_per_sec = FLAGS.batch_size / float(duration)
                print('%s: step %d, loss = %.2f (%.1f examples/sec; %.3f sec/batch)' % 
                    (datetime.now(), step, loss_value, examples_per_sec, duration))

            # Write the summary periodically.
            if step % FLAGS.summary_steps == 0:
                summary_str, x_summary_str, y_summary_str = sess.run([summary_op, x_summary, y_summary],
                                                                     feed_dict={phase_train: is_train,
                                                                     x: x_batch, y: y_batch})
                summary_writer.add_summary(summary_str, step)
                
                x_summary_tmp = tf.Summary()
                y_summary_tmp = tf.Summary()
                x_summary_tmp.ParseFromString(x_summary_str)
                y_summary_tmp.ParseFromString(y_summary_str)
                for i in xrange(FLAGS.max_images):
                    x_summary_tmp.value[i].tag = '%06d/%03d_x' % (step, i)
                    y_summary_tmp.value[i].tag = '%06d/%03d_y' % (step, i)
                summary_writer.add_summary(x_summary_tmp, step)
                summary_writer.add_summary(y_summary_tmp, step)

            # Save the model checkpoint periodically.
            if (step + 1) % FLAGS.save_steps == 0 or (step + 1) == FLAGS.max_steps:
                checkpoint_path = os.path.join(FLAGS.log_dir, 'linenet.ckpt')
                saver.save(sess, checkpoint_path)

        print('done')


def main(_):
    # if release mode, change current path
    current_path = os.getcwd()
    if not current_path.endswith('linenet'):
        working_path = os.path.join(current_path, 'vectornet/linenet')
        os.chdir(working_path)
        
    # create log directory
    if FLAGS.log_dir.endswith('log'):
        FLAGS.log_dir = os.path.join(FLAGS.log_dir, datetime.now().isoformat().replace(':', '-'))
    elif tf.gfile.Exists(FLAGS.log_dir):
        tf.gfile.DeleteRecursively(FLAGS.eval_dir)
    tf.gfile.MakeDirs(FLAGS.log_dir)

    # start training
    train()

if __name__ == '__main__':
    tf.app.run()
