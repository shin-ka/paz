
import numpy as np
import tensorflow as tf

from tensorflow.keras.layers import MaxPool2D
from tensorflow.keras.layers import Conv2D
from tensorflow.keras.layers import BatchNormalization
from tensorflow.keras.layers import ReLU
from tensorflow.keras.layers import Input
from tensorflow.keras.layers import concatenate
from tensorflow.keras.regularizers import l2
from tensorflow.keras.initializers import VarianceScaling
from tensorflow.keras.initializers import truncated_normal
from tensorflow.keras.models import Model


def zero_padding(tensor, pad_1, pad_2):
    pad_mat = np.array([[0, 0],
                        [pad_1, pad_2],
                        [pad_1, pad_2],
                        [0, 0]])
    return tf.pad(tensor, paddings=pad_mat)


def block(tensor, filters, kernel_size, strides, name, training,
          rate=1, with_relu=True):
    if strides == 1:
        x = Conv2D(filters, kernel_size, strides, padding='SAME',
                   use_bias=False, dilation_rate=rate,
                   kernel_regularizer=l2(0.5 * 1.0), name=name + '/conv2d',
                   kernel_initializer=VarianceScaling(
                       mode="fan_avg", distribution="uniform"))(tensor)
    else:
        pad_1 = (kernel_size - 1) // 2
        pad_2 = (kernel_size - 1) - pad_1
        x = zero_padding(tensor, pad_1, pad_2)
        x = Conv2D(filters, kernel_size, strides, padding='VALID',
                   use_bias=False, dilation_rate=rate,
                   kernel_regularizer=l2(0.5 * (1.0)), name=name + '/conv2d',
                   kernel_initializer=VarianceScaling(
                       mode="fan_avg", distribution="uniform"))(x)
    x = BatchNormalization(name=name + '/batch_normalization')(x, training)
    if with_relu:
        x = ReLU()(x)
    return x


def bottleneck(tensor, filters, strides, name, training, rate=1):
    shape = tensor.get_shape()[-1]
    if shape == filters:
        if strides == 1:
            x = tensor
        else:
            x = MaxPool2D(strides, strides, 'SAME')(tensor)
    else:
        x = block(tensor, filters, 1, strides, name + '/shortcut',
                  training, with_relu=False)
    residual = block(tensor, (filters // 4), 1, 1, name + '/conv1', training)
    residual = block(residual, (filters // 4), 3, strides, name + '/conv2',
                     training, rate)
    residual = block(residual, filters, 1, 1, name + '/conv3', training,
                     with_relu=False)
    output = ReLU()(x + residual)
    return output


def resnet50(tensor, name, training):
    x = block(tensor, 64, 7, 2, name + '/conv1', training)

    for arg in range(2):
        x = bottleneck(x, 256, 1, name + '/block1/unit%d' % (arg+1), training)
    x = bottleneck(x, 256, 2, name + '/block1/unit3', training)

    for arg in range(4):
        x = bottleneck(x, 512, 1, name + '/block2/unit%d' % (arg+1),
                       training, 2)

    for arg in range(6):
        x = bottleneck(x, 1024, 1, name + '/block3/unit%d' % (arg+1),
                       training, 4)

    x = block(x, 256, 3, 1, name + '/squeeze', training)
    return x


def net_2d(features, num_keypoints, name, training=False):
    x = block(features, 256, 3, 1, name + '/project', training)
    hmap = Conv2D(num_keypoints, 1, strides=1, padding='SAME',
                  activation=tf.sigmoid, name=name + '/prediction/conv2d',
                  kernel_initializer=truncated_normal(stddev=0.01))(x)
    return hmap


def net_3d(features, num_keypoints, name, need_norm=False, training=False):
    x = block(features, 256, 3, 1, name + '/project', training)
    dmap = Conv2D(num_keypoints * 3, 1, strides=1, padding='SAME',
                  name=name + '/prediction/conv2d',
                  kernel_initializer=truncated_normal(stddev=0.01))(x)
    if need_norm:
        dmap_norm = tf.norm(dmap, axis=-1, keepdims=True)
        dmap = dmap / tf.maximum(dmap_norm, 1e-6)

    H, W = features.get_shape()[1:3]
    dmap = tf.reshape(dmap, [-1, H, W, num_keypoints, 3])
    if need_norm:
        return dmap, dmap_norm
    return dmap


def get_pose_tile(N):
    x = np.linspace(-1, 1, 32)
    x = np.stack([np.tile(x.reshape([1, 32]), [32, 1]),
                  np.tile(x.reshape([32, 1]), [1, 32])], -1)
    x = np.expand_dims(x, 0)
    x = tf.constant(x, dtype=tf.float32)
    pose_tile = tf.tile(x, [N, 1, 1, 1])
    return pose_tile


def tf_hmap_to_uv(hmap):
    shape = tf.shape(hmap)
    hmap = tf.reshape(hmap, (shape[0], -1, shape[3]))
    argmax = tf.math.argmax(hmap, axis=1, output_type=tf.int32)
    argmax_x = argmax // shape[2]
    argmax_y = argmax % shape[2]
    uv = tf.stack((argmax_x, argmax_y), axis=1)
    uv = tf.transpose(a=uv, perm=[0, 2, 1])
    return uv


def DetNet(input_shape=(128, 128, 3), num_keypoints=21):
    """
    DetNet: Estimating 3D keypoint positions from input color image.
    # Arguments
    -------
        input_shape: Shape for 128x128 RGB image of **left hand**.
                     List of integers. Input shape to the model including only
                     spatial and channel resolution e.g. (128, 128, 3).
        num_keypoints: Int. Number of keypoints.

    Returns
    -------
    xvy: np.ndarray, shape [21, 3]
      Normalized 3D keypoint locations.
    np.ndarray, shape [21, 2]
      The uv coordinates of the keypoints on the heat map, whose resolution is
      32x32.
    np.ndarray, shape [21, 3]
      Orientaion of the bone

    # Reference
    -------
        - [Monocular Real-time Hand Shape and Motion Capture using Multi-modal
           Data](https://arxiv.org/abs/2003.09572)
    """

    image = Input(shape=input_shape, dtype=tf.uint8)
    x = tf.cast(image, tf.float32) / 255

    name = 'prior_based_hand'
    features = resnet50(x, name + '/resnet', False)
    pose_tile = get_pose_tile(tf.shape(x)[0])
    features = concatenate([features, pose_tile], -1)

    hmaps = []
    dmaps = []
    lmaps = []
    n_stack = 1
    for i in range(n_stack):
        hmap = net_2d(features, num_keypoints, name + '/hmap_%d' % i, False)
        hmaps.append(hmap)
        features = concatenate([features, hmap], axis=-1)

        dmap = net_3d(features, num_keypoints, name + '/dmap_%d' % i, False)
        dmaps.append(dmap)
        dmap = tf.reshape(dmap, [-1, 32, 32, num_keypoints * 3])
        features = concatenate([features, dmap], -1)

        lmap = net_3d(features, num_keypoints, name + '/lmap_%d' % i, False)
        lmaps.append(lmap)
        lmap = tf.reshape(lmap, [-1, 32, 32, num_keypoints * 3])
        features = concatenate([features, lmap], -1)

    hmap = hmaps[-1]
    dmap = dmaps[-1]
    lmap = lmaps[-1]

    uv = tf_hmap_to_uv(hmap)
    delta = tf.gather_nd(
        tf.transpose(dmap, perm=[0, 3, 1, 2, 4]), uv, batch_dims=2)[0]
    xyz = tf.gather_nd(
        tf.transpose(lmap, perm=[0, 3, 1, 2, 4]), uv, batch_dims=2)[0]

    uv = uv[0]

    model = Model(image, outputs=[xyz, uv, delta])
    model_path = 'model_weights/detnet_weights.hdf5'
    model.load_weights(model_path)
    return model
