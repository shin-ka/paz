import numpy as np
import tensorflow as tf
from munkres import Munkres
import cv2


SCALING_FACTOR = 200.0
PIXEL_SIZE = 64
MIN_SCALE = 1
INPUT_SIZE = 512


def resize_dims(current_scale, min_input_size, dims1, dims2):
    '''resize to 512'''
    dims1_resized = int(min_input_size * current_scale / MIN_SCALE)
    dims2_resized = int(int((min_input_size / dims1*dims2 + (PIXEL_SIZE-1)) //
                        PIXEL_SIZE*PIXEL_SIZE) * current_scale/MIN_SCALE)
    scale_dims1 = dims1 / SCALING_FACTOR
    scale_dims2 = dims2_resized / dims1_resized * dims1 / SCALING_FACTOR
    return dims1_resized, dims2_resized, scale_dims1, scale_dims2


def calculate_image_center(image):
    H, W = image.shape[:2]
    center_W = W / 2.0
    center_H = H / 2.0
    return center_W, center_H


def calculate_min_input_size():
    min_input_size = int((MIN_SCALE * INPUT_SIZE + (PIXEL_SIZE-1)) //
                         PIXEL_SIZE*PIXEL_SIZE)
    return min_input_size


def rotate_point(point2D, rotation_angle):
    rotation_angle = np.pi * rotation_angle / 180
    sn, cs = np.sin(rotation_angle), np.cos(rotation_angle)
    x_rotated = (point2D[0] * cs) - (point2D[1] * sn)
    y_rotated = (point2D[0] * sn) + (point2D[1] * cs)
    return [x_rotated, y_rotated]


def calculate_third_point(point2D_a, point2D_b):
    diff = point2D_a - point2D_b
    return point2D_a + np.array([-diff[1], diff[0]], dtype=np.float32)


def construct_source_image(scale, center, shift=np.array([0., 0.])):
    scale = scale * SCALING_FACTOR
    image_W = scale[0]
    image_dir = rotate_point([0, image_W * -0.5], 0)
    image = np.zeros((3, 2), dtype=np.float32)
    image[0, :] = center + scale * shift
    image[1, :] = center + image_dir + scale * shift
    image[2:, :] = calculate_third_point(image[0, :], image[1, :])
    return image


def construct_output_image(output_size):
    W = output_size[0]
    H = output_size[1]
    image_dir = np.array([0, W * -0.5], np.float32)
    image = np.zeros((3, 2), dtype=np.float32)
    image[0, :] = [W * 0.5, H * 0.5]
    image[1, :] = np.array([W * 0.5, H * 0.5]) + image_dir
    image[2:, :] = calculate_third_point(image[0, :], image[1, :])
    return image

