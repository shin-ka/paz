import numpy as np
import tensorflow as tf
from paz import processors as pr
from munkres import Munkres
import cv2
import PIL
from backend.preprocess import resize_dims
from backend.preprocess import calculate_image_center
from backend.preprocess import calculate_min_input_size
from backend.preprocess import construct_source_image
from backend.preprocess import construct_output_image

from backend.tensorflow_functions import load_model
# from backend.tensorflow_functions import max_pooling2D
# from backend.tensorflow_functions import transpose_tensor
# from backend.tensorflow_functions import elementwise_equality
# from backend.tensorflow_functions import cast_tensor
# from backend.tensorflow_functions import reshape_tensor
# from backend.tensorflow_functions import where_true
# from backend.tensorflow_functions import fill_tensor
# from backend.tensorflow_functions import stack_tensors
# from backend.tensorflow_functions import gather_nd
# from backend.tensorflow_functions import find_k_largest_entries
# from backend.tensorflow_functions import up_sampling2D
# from backend.tensorflow_functions import concatenate_tensors

from backend.heatmaps import non_maximum_supressions, match_by_tag, top_k_keypoints
from backend.heatmaps import adjust_heatmaps, refine_heatmaps, convert_to_numpy


class LoadModel(pr.Processor):
    def __init__(self):
        super(LoadModel, self).__init__()

    def call(self, model_path):
        return load_model(model_path)


class LoadImage(pr.Processor):
    def __init__(self):
        super(LoadImage, self).__init__()

    def call(self, image_path):
        return np.array(PIL.Image.open(image_path, 'r')).astype(np.uint8)


class NonMaximumSuppression(pr.Processor):
    def __init__(self):
        super(NonMaximumSuppression, self).__init__()

    def call(self, detection_boxes):
        filtered_box = non_maximum_supressions(detection_boxes)
        return filtered_box


class MatchByTag(pr.Processor):
    def __init__(self):
        super(MatchByTag, self).__init__()

    def call(self, input_):
        return match_by_tag(input_)


class TopK_Keypoints(pr.Processor):
    def __init__(self):
        super(TopK_Keypoints, self).__init__()

    def call(self, boxes, tag):
        keypoints = top_k_keypoints(boxes, tag)
        return keypoints


class AdjustKeypoints(pr.Processor):
    def __init__(self):
        super(AdjustKeypoints, self).__init__()

    def call(self, boxes, keypoints):
        keypoints = adjust_heatmaps(boxes, keypoints)
        return keypoints


class RefineKeypoints(pr.Processor):
    def __init__(self):
        super(RefineKeypoints, self).__init__()

    def call(self, boxes, keypoints, tag):
        keypoints = refine_heatmaps(boxes, keypoints, tag)
        return keypoints


class GetScores(pr.Processor):
    def __init__(self):
        super(GetScores, self).__init__()

    def call(self, ans):
        score = [i[:, 2].mean() for i in ans]
        return score


class ConvertToNumpy(pr.Processor):
    def __init__(self):
        super(ConvertToNumpy, self).__init__()

    def call(self, boxes, tag):
        return convert_to_numpy(boxes, tag)


class ResizeDimensions(pr.Processor):
    def __init__(self):
        super(ResizeDimensions, self).__init__()

    def call(self, current_scale, min_input_size, dims1, dims2):
        dims1_resized, dims2_resized, scale_dims1, scale_dims2 = \
            resize_dims(current_scale, min_input_size, dims1, dims2)
        return dims1_resized, dims2_resized, scale_dims1, scale_dims2


class GetImageCenter(pr.Processor):
    def __init__(self, offset=0.5):
        super(GetImageCenter, self).__init__()
        self.offset = offset

    def call(self, image):
        center_W, center_H = calculate_image_center(image)
        center_W = int(center_W + self.offset)
        center_H = int(center_H + self.offset)
        return np.array([center_W, center_H])


class MinInputSize(pr.Processor):
    def __init__(self):
        super(MinInputSize, self).__init__()

    def call(self):
        min_input_size = calculate_min_input_size()
        return min_input_size


class ConstructSourceImage(pr.Processor):
    def __init__(self):
        super(ConstructSourceImage, self).__init__()

    def call(self, scale, center):
        source_image = construct_source_image(scale, center)
        return source_image


class ConstructOutputImage(pr.Processor):
    def __init__(self):
        super(ConstructOutputImage, self).__init__()

    def call(self, output_size):
        output_image = construct_output_image(output_size)
        return output_image


class GetAffineTransform(pr.Processor):
    def __init__(self):
        super(GetAffineTransform, self).__init__()

    def call(self, dst, src):
        transform = cv2.getAffineTransform(np.float32(dst), np.float32(src))
        return transform


class WarpAffine(pr.Processor):
    def __init__(self):
        super(WarpAffine, self).__init__()

    def call(self, image, transform, size_resized):
        image_resized = cv2.warpAffine(image, transform, size_resized)
        return image_resized


class UpSampling2D(pr.Processor):
    def __init__(self, size, interpolation):
        super(UpSampling2D, self).__init__()
        self.size = size
        self.interpolation = interpolation

    def call(self, x):
        if isinstance(x, list):
            x = [tf.keras.layers.UpSampling2D(size=self.size,
                 interpolation=self.interpolation)(each) for each in x]
        else:
            x = \
             tf.keras.layers.UpSampling2D(size=self.size,
                                          interpolation=self.interpolation)(x)
        return x


class CalculateHeatmapAverage(pr.Processor):
    def __init__(self):
        super(CalculateHeatmapAverage, self).__init__()

    def call(self, heatmaps):
        heatmaps_average = (heatmaps[0] + heatmaps[1])/2.0
        return heatmaps_average


class IncrementByOne(pr.Processor):
    def __init__(self):
        super(IncrementByOne, self).__init__()

    def call(self, x):
        x += 1
        return x


class UpdateHeatmapAverage(pr.Processor):
    def __init__(self):
        super(UpdateHeatmapAverage, self).__init__()

    def call(self, heatmaps_average, output, indices,
             num_joints, with_flip=False):
        if not with_flip:
            heatmaps_average += output[:, :, :, :num_joints]
        else:
            temp = output[:, :, :, :num_joints]
            heatmaps_average += tf.gather(temp, indices, axis=-1)
        return heatmaps_average


class UpdateTags(pr.Processor):
    def __init__(self, tag_per_joint):
        super(UpdateTags, self).__init__()
        self.tag_per_joint = tag_per_joint

    def call(self, tags, output, offset, indices, with_flip=False):
        tags.append(output[:, :, :, offset:])
        if with_flip and self.tag_per_joint:
            tags[-1] = tf.gather(tags[-1], indices, axis=-1)
        return tags


class UpdateHeatmaps(pr.Processor):
    def __init__(self):
        super(UpdateHeatmaps, self).__init__()

    def call(self, heatmaps, heatmap_average, num_heatmaps):
        heatmaps.append(heatmap_average/num_heatmaps)
        return heatmaps


class CalculateOffset(pr.Processor):
    def __init__(self, num_joints, loss_with_heatmap_loss):
        super(CalculateOffset, self).__init__()
        self.num_joints = num_joints
        self.loss_with_heatmap_loss = loss_with_heatmap_loss

    def call(self, idx):
        if self.loss_with_heatmap_loss[idx]:
            offset = self.num_joints
        else:
            offset = 0
        return offset


class FlipJointOrder(pr.Processor):
    def __init__(self, with_center):
        super(FlipJointOrder, self).__init__()
        self.with_center = with_center

    def call(self):
        if not self.with_center:
            idx = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10,
                   9, 12, 11, 14, 13, 16, 15]
        else:
            idx = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10,
                   9, 12, 11, 14, 13, 16, 15, 17]
        return idx


class RemoveLastElement(pr.Processor):
    def __init__(self):
        super(RemoveLastElement, self).__init__()

    def call(self, nested_list):
        return [each_list[:, :-1] for each_list in nested_list]


class PostProcessHeatmaps(pr.Processor):
    def __init__(self, test_scale_factor):
        super(PostProcessHeatmaps, self).__init__()
        self.test_scale_factor = test_scale_factor

    def call(self, heatmaps):
        heatmaps = heatmaps/float(len(self.test_scale_factor))
        heatmaps = tf.transpose(heatmaps, [0, 3, 1, 2])
        return heatmaps


class PostProcessTags(pr.Processor):
    def __init__(self):
        super(PostProcessTags, self).__init__()

    def call(self, tags):
        tags = tf.concat(tags, axis=4)
        tags = tf.transpose(tags, [0, 3, 1, 2, 4])
        return tags


class AffineTransformPoint(pr.Processor):
    def __init__(self):
        super(AffineTransformPoint, self).__init__()

    def call(self, point, transform):
        point = np.array([point[0], point[1], 1.]).T
        point_transformed = np.dot(transform, point)
        return point_transformed[:2]
