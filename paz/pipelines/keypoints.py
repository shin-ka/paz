from ..abstract import SequentialProcessor, Processor
from .. import processors as pr

from .renderer import RenderTwoViews
from ..models import KeypointNet2D
from tensorflow.keras.utils import get_file
from ..backend.image import get_affine_transform


class KeypointNetSharedAugmentation(SequentialProcessor):
    """Wraps ``RenderTwoViews`` as a sequential processor for using it directly
        with a ``paz.GeneratingSequence``.

    # Arguments
        renderer: ``RenderTwoViews`` processor.
        size: Image size.
    """
    def __init__(self, renderer, size):
        super(KeypointNetSharedAugmentation, self).__init__()
        self.renderer = renderer
        self.size = size
        self.add(RenderTwoViews(self.renderer))
        self.add(pr.SequenceWrapper(
            {0: {'image_A': [size, size, 3]},
             1: {'image_B': [size, size, 3]}},
            {2: {'matrices': [4, 4 * 4]},
             3: {'alpha_channels': [size, size, 2]}}))


class KeypointNetInference(Processor):
    """Performs inference from a ``KeypointNetShared`` model.

    # Arguments
        model: Keras model for predicting keypoints.
        num_keypoints: Int or None. If None ``num_keypoints`` is
            tried to be inferred from ``model.output_shape``
        radius: Int. used for drawing the predicted keypoints.
    """
    def __init__(self, model, num_keypoints=None, radius=5):
        super(KeypointNetInference, self).__init__()
        self.num_keypoints, self.radius = num_keypoints, radius
        if self.num_keypoints is None:
            self.num_keypoints = model.output_shape[1]

        preprocessing = SequentialProcessor()
        preprocessing.add(pr.NormalizeImage())
        preprocessing.add(pr.ExpandDims(axis=0))
        self.predict_keypoints = SequentialProcessor()
        self.predict_keypoints.add(pr.Predict(model, preprocessing))
        self.predict_keypoints.add(pr.SelectElement(0))
        self.predict_keypoints.add(pr.Squeeze(axis=0))
        self.postprocess_keypoints = SequentialProcessor()
        self.postprocess_keypoints.add(pr.DenormalizeKeypoints())
        self.postprocess_keypoints.add(pr.RemoveKeypointsDepth())
        self.draw = pr.DrawKeypoints2D(self.num_keypoints, self.radius, False)
        self.wrap = pr.WrapOutput(['image', 'keypoints'])

    def call(self, image):
        keypoints = self.predict_keypoints(image)
        keypoints = self.postprocess_keypoints(keypoints, image)
        image = self.draw(image, keypoints)
        return self.wrap(image, keypoints)


class EstimateKeypoints2D(Processor):
    """Basic 2D keypoint prediction pipeline.

    # Arguments
        model: Keras model for predicting keypoints.
        num_keypoints: Int or None. If None ``num_keypoints`` is
            tried to be inferred from ``model.output_shape``
        draw: Boolean indicating if inferences should be drawn.
        radius: Int. used for drawing the predicted keypoints.
    """
    def __init__(self, model, num_keypoints, draw=True, radius=3,
                 color=pr.RGB2BGR):
        self.model = model
        self.num_keypoints = num_keypoints
        self.draw, self.radius, self.color = draw, radius, color
        self.preprocess = SequentialProcessor()
        self.preprocess.add(pr.ResizeImage(self.model.input_shape[1:3]))
        self.preprocess.add(pr.ConvertColorSpace(self.color))
        self.preprocess.add(pr.NormalizeImage())
        self.preprocess.add(pr.ExpandDims(0))
        self.preprocess.add(pr.ExpandDims(-1))
        self.predict = pr.Predict(model, self.preprocess, pr.Squeeze(0))
        self.denormalize = pr.DenormalizeKeypoints()
        self.draw = pr.DrawKeypoints2D(self.num_keypoints, self.radius, False)
        self.wrap = pr.WrapOutput(['image', 'keypoints'])

    def call(self, image):
        keypoints = self.predict(image)
        keypoints = self.denormalize(keypoints, image)
        if self.draw:
            image = self.draw(image, keypoints)
        return self.wrap(image, keypoints)


class FaceKeypointNet2D32(EstimateKeypoints2D):
    """KeypointNet2D model trained with Kaggle Facial Detection challenge.

    # Arguments
        draw: Boolean indicating if inferences should be drawn.
        radius: Int. used for drawing the predicted keypoints.

    # Example
        ``` python
        from paz.pipelines import FaceKeypointNet2D32

        estimate_keypoints= FaceKeypointNet2D32()

        # apply directly to an image (numpy-array)
        inference = estimate_keypoints(image)
        ```
    # Returns
        A function that takes an RGB image and outputs the predictions
        as a dictionary with ``keys``: ``image`` and ``keypoints``.
        The corresponding values of these keys contain the image with the drawn
        inferences and a numpy array representing the keypoints.
    """
    def __init__(self, draw=True, radius=3):
        model = KeypointNet2D((96, 96, 1), 15, 32, 0.1)
        self.weights_URL = ('https://github.com/oarriaga/altamira-data/'
                            'releases/download/v0.7/')
        weights_path = self.get_weights_path(model)
        model.load_weights(weights_path)
        super(FaceKeypointNet2D32, self).__init__(
            model, 15, draw, radius, pr.RGB2GRAY)

    def get_weights_path(self, model):
        model_name = '_'.join(['FaceKP', model.name, '32', '15'])
        model_name = '%s_weights.hdf5' % model_name
        URL = self.weights_URL + model_name
        return get_file(model_name, URL, cache_subdir='paz/models')


class GetKeypoints(pr.Processor):
    """Extract out the top k keypoints heatmaps and group the keypoints with
       their respective tags value. Adjust and refine the keypoint locations
       by removing the margins.
    # Arguments
        max_num_instance: Int. Maximum number of instances to be detected.
        keypoint_order: List of length 17 (number of keypoints).
        heatmaps: Numpy array of shape (1, num_keypoints, H, W)
        Tags: Numpy array of shape (1, num_keypoints, H, W, 2)

    # Returns
        grouped_keypoints: numpy array. keypoints grouped by tag
        scores: int: score for the keypoint
    """
    def __init__(self, max_num_instance, keypoint_order, detection_thresh=0.2,
                 tag_thresh=1):
        super(GetKeypoints, self).__init__()
        self.group_keypoints = pr.SequentialProcessor(
            [pr.TopKDetections(max_num_instance), pr.GroupKeypointsByTag(
                keypoint_order, tag_thresh, detection_thresh)])
        self.adjust_keypoints = pr.AdjustKeypointsLocations()
        self.get_scores = pr.GetScores()
        self.refine_keypoints = pr.RefineKeypointsLocations()

    def call(self, heatmaps, tags, adjust=True, refine=True):
        grouped_keypoints = self.group_keypoints(heatmaps, tags)
        if adjust:
            grouped_keypoints = self.adjust_keypoints(
                heatmaps, grouped_keypoints)[0]
        scores = self.get_scores(grouped_keypoints)
        if refine:
            grouped_keypoints = self.refine_keypoints(
                heatmaps[0], tags[0], grouped_keypoints)
        return grouped_keypoints, scores


class TransformKeypoints(pr.Processor):
    """Transform the keypoint coordinates.
    # Arguments
        grouped_keypoints: Numpy array. keypoints grouped by tag
        center: Tuple. center of the imput image
        scale: Float. scaled imput image dimension
        shape: Tuple/List

    # Returns
        transformed_keypoints: keypoint location with respect to the
                               input image
    """
    def __init__(self, inverse=False):
        super(TransformKeypoints, self).__init__()
        self.inverse = inverse
        self.get_source_destination_point = pr.GetSourceDestinationPoints(
            scaling_factor=200)
        self.transform_keypoints = pr.TransformKeypoints()

    def call(self, grouped_keypoints, center, scale, shape):
        source_point, destination_point = self.get_source_destination_point(
            center, scale, shape)
        if self.inverse:
            source_point, destination_point = destination_point, source_point
        transform = get_affine_transform(source_point, destination_point)
        transformed_keypoints = self.transform_keypoints(grouped_keypoints,
                                                         transform)
        return transformed_keypoints
