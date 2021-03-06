from __future__ import division, print_function, absolute_import

import tensorflow as tf
import matplotlib.pyplot as plt
import numpy as np


class CNN:
    def __init__(self, dataset, label2ind, ind2label, test_set_percent=0.2, learning_rate=0.001, num_steps=2000,
                 batch_size=128, num_input=784,
                 dropout=0.25):
        # Checkpoint Settings
        self.model_dir = "./ckpts/"
        self.output_node_names = "output"

        # Training Parameters
        self.learning_rate = learning_rate
        self.num_steps = num_steps
        self.batch_size = 128

        # Network Parameters
        self.num_input = num_input
        self.num_classes = len(label2ind)
        self.dropout = dropout

        # Problem Parameters
        self.label2ind = label2ind
        self.ind2label = ind2label

        # dataset
        self.prepare_dataset(dataset, test_set_percent)

        self.setup_network()

        self.feature_spec = {"image": tf.VarLenFeature(dtype=np.float32)}

    def serving_input_receiver_fn(self):
        serialized_tf_example = tf.placeholder(dtype=tf.string,
                                               # shape=[1, 28, 28, 1],
                                               name='serving_input_char')
        receiver_tensors = {'examples': serialized_tf_example}
        features = tf.parse_example(serialized_tf_example, self.feature_spec)
        return tf.estimator.export.ServingInputReceiver(features, receiver_tensors)

    def prepare_dataset(self, dataset, test_set_percent):
        dataset_count = np.sum([len(dataset[d]) for d in dataset])
        train_set_count = int(dataset_count * (1 - test_set_percent))
        test_set_count = dataset_count - train_set_count
        self.train_images = np.zeros(shape=(train_set_count + 1, 28, 28, 1), dtype=np.float32)
        self.train_labels = np.zeros(shape=train_set_count + 1, dtype=np.float32)
        self.test_images = np.zeros(shape=(test_set_count + 23, 28, 28, 1), dtype=np.float32)
        self.test_labels = np.zeros(shape=test_set_count + 23, dtype=np.float32)
        train_ind = 0
        test_ind = 0
        for class_ind in dataset:
            data = dataset[class_ind]
            print("indexing images from class number: ", class_ind, " with total images: ", len(data))
            for i in range(len(data)):
                if i < int(len(data) * (1 - test_set_percent)):
                    self.train_images[train_ind, :, :, 0] = data[i]
                    self.train_labels[train_ind] = class_ind
                    train_ind += 1
                else:
                    self.test_images[test_ind, :, :, 0] = data[i]
                    self.test_labels[test_ind] = class_ind
                    test_ind += 1

    # Create the neural network
    def conv_net(self, x_dict, n_classes, dropout, reuse, is_training):
        # Define a scope for reusing the variables
        with tf.variable_scope('Input', reuse=reuse):
            # TF Estimator input is a dict, in case of multiple inputs
            x = x_dict['images']
            # MNIST data input is a 1-D vector of 784 features (28*28 pixels)
            # Reshape to match picture format [Height x Width x Channel]
            # Tensor input become 4-D: [Batch Size, Height, Width, Channel]
            x = tf.reshape(x, shape=[-1, 28, 28, 1])

        with tf.variable_scope('Conv1', reuse=reuse):
            # Convolution Layer with 32 filters and a kernel size of 5
            conv1 = tf.layers.conv2d(x, 32, 5, activation=tf.nn.relu)
            # Max Pooling (down-sampling) with strides of 2 and kernel size of 2
            conv1 = tf.layers.max_pooling2d(conv1, 2, 2)

        with tf.variable_scope('Conv2', reuse=reuse):
            # Convolution Layer with 64 filters and a kernel size of 3
            conv2 = tf.layers.conv2d(conv1, 64, 3, activation=tf.nn.relu)
            # Max Pooling (down-sampling) with strides of 2 and kernel size of 2
            conv2 = tf.layers.max_pooling2d(conv2, 2, 2)

        with tf.variable_scope('FC1', reuse=reuse):
            # Flatten the data to a 1-D vector for the fully connected layer
            fc1 = tf.contrib.layers.flatten(conv2)

            # Fully connected layer (in tf contrib folder for now)
            fc1 = tf.layers.dense(fc1, 1024)
            # Apply Dropout (if is_training is False, dropout is not applied)
            fc1 = tf.layers.dropout(fc1, rate=dropout, training=is_training)

        with tf.variable_scope('Logits', reuse=reuse):
            # Output layer, class prediction
            out = tf.layers.dense(fc1, n_classes)

        return out

    # Define the model function (following TF Estimator Template)
    def model_fn(self, features, labels, mode):
        # Build the neural network
        # Because Dropout have different behavior at training and prediction time, we
        # need to create 2 distinct computation graphs that still share the same weights.
        logits_train = self.conv_net(features, self.num_classes, self.dropout,
                                     reuse=False, is_training=True)
        logits_test = self.conv_net(features, self.num_classes, self.dropout,
                                    reuse=True, is_training=False)

        # Predictions
        pred_classes = tf.argmax(logits_test, axis=1)
        pred_probas = tf.nn.softmax(logits_test, name="output")

        # If prediction mode, early return
        if mode == tf.estimator.ModeKeys.PREDICT:
            return tf.estimator.EstimatorSpec(mode, predictions=pred_classes,
                                              export_outputs=
                                              {"preds": tf.estimator.export.PredictOutput(outputs=pred_classes)})

            # Define loss and optimizer
        loss_op = tf.reduce_mean(tf.nn.sparse_softmax_cross_entropy_with_logits(
            logits=logits_train, labels=tf.cast(labels, dtype=tf.int32)))
        optimizer = tf.train.AdamOptimizer(learning_rate=self.learning_rate)
        train_op = optimizer.minimize(loss_op, global_step=tf.train.get_global_step())

        # Evaluate the accuracy of the model
        acc_op = tf.metrics.accuracy(labels=labels, predictions=pred_classes)

        # TF Estimators requires to return a EstimatorSpec, that specify
        # the different ops for training, evaluating, ...
        estim_specs = tf.estimator.EstimatorSpec(
            mode=mode,
            predictions=pred_classes,
            loss=loss_op,
            train_op=train_op,
            eval_metric_ops={'accuracy': acc_op})

        return estim_specs

    def setup_network(self):
        # Build the Estimato
        self.model = tf.estimator.Estimator(self.model_fn,
                                            # model_dir=self.model_dir
                                            )

        # Define the input function for training
        self.input_fn = tf.estimator.inputs.numpy_input_fn(
            x={'images': self.train_images}, y=self.train_labels,
            batch_size=self.batch_size, num_epochs=None, shuffle=True)

    def train(self):
        # Train the Model
        self.model.train(self.input_fn, steps=self.num_steps)

        # Evaluate the Model
        # Define the input function for evaluating
        input_fn = tf.estimator.inputs.numpy_input_fn(
            x={'images': self.test_images}, y=self.test_labels,
            batch_size=self.batch_size, shuffle=False)
        # Use the Estimator 'evaluate' method
        print(self.model.evaluate(input_fn))

        # simple_save(session=self.model.se)
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO
        #TODO

        self.test_model()

        # self.export_model()

    def test_model(self):
        # Predict single images
        n_images = 1
        # Get images from test set
        self.test_images = self.test_images[:n_images]
        # Prepare the input data
        input_fn = tf.estimator.inputs.numpy_input_fn(
            x={'images': self.test_images}, shuffle=False)
        # Use the model to predict the images class
        preds = list(self.model.predict(input_fn))
        # Display
        for i in range(n_images):
            plt.imshow(np.reshape(self.test_images[i], [28, 28]), cmap='gray')
            plt.show()
            print("Model prediction:", self.ind2label[preds[i]])

    def predict_single_image(self, image):
        input_fn = tf.estimator.inputs.numpy_input_fn(x={'images': image}, shuffle=False)
        pred = list(self.model.predict(input_fn))
        # print(pred)
        pred = self.ind2label[pred[0]]
        return pred

    def export_model(self):
        self.model.export_saved_model(
            # export_dir_base=self.model_dir,
                                      serving_input_receiver_fn=self.serving_input_receiver_fn)

    def freeze(self):
        """Extract the sub graph defined by the output nodes and convert
        all its variables into constant
        Args:
            model_dir: the root folder containing the checkpoint state file
            output_node_names: a string, containing all the output node's names,
                                comma separated
        """
        if not tf.gfile.Exists(self.model_dir):
            raise AssertionError(
                "Export directory doesn't exists. Please specify an export "
                "directory: %s" % self.model_dir)

        if not self.output_node_names:
            print("You need to supply the name of a node to --output_node_names.")
            return -1

        # We retrieve our checkpoint fullpath
        checkpoint = tf.train.get_checkpoint_state(self.model_dir)
        input_checkpoint = checkpoint.model_checkpoint_path

        # We precise the file fullname of our freezed graph
        absolute_model_dir = "/".join(input_checkpoint.split('/')[:-1])
        output_graph = absolute_model_dir + "/frozen_model.pb"

        # We clear devices to allow TensorFlow to control on which device it will load operations
        clear_devices = True

        # We start a session using a temporary fresh Graph
        with tf.Session(graph=tf.Graph()) as sess:
            # We import the meta graph in the current default Graph
            saver = tf.train.import_meta_graph(input_checkpoint + '.meta', clear_devices=clear_devices)

            # We restore the weights
            saver.restore(sess, input_checkpoint)

            # We use a built-in TF helper to export variables to constants
            output_graph_def = tf.graph_util.convert_variables_to_constants(
                sess,  # The session is used to retrieve the weights
                tf.get_default_graph().as_graph_def(),  # The graph_def is used to retrieve the nodes
                self.output_node_names.split(",")  # The output node names are used to select the usefull nodes
            )

            # Finally we serialize and dump the output graph to the filesystem
            with tf.gfile.GFile(output_graph, "wb") as f:
                f.write(output_graph_def.SerializeToString())
            print("%d ops in the final graph." % len(output_graph_def.node))

        return output_graph_def

    def load_graph(self):
        # We load the protobuf file from the disk and parse it to retrieve the
        # unserialized graph_def
        with tf.gfile.GFile(self.model_dir + "/frozen_model.pb", "rb") as f:
            graph_def = tf.GraphDef()
            graph_def.ParseFromString(f.read())

        # Then, we import the graph_def into a new Graph and returns it
        with tf.Graph().as_default() as graph:
            # The name var will prefix every op/nodes in your graph
            # Since we load everything in a new graph, this is not needed
            tf.import_graph_def(graph_def, name="frozen")
        return graph
