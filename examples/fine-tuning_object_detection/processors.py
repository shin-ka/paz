from paz.abstract import Processor
from boxes import match
from backend import load_image


class LoadImage(Processor):
    """Loads image.

    # Arguments
        num_channels: Integer, valid integers are: 1, 3 and 4.
    """
    def __init__(self, num_channels=3):
        self.num_channels = num_channels
        super(LoadImage, self).__init__()

    def call(self, image):
        return load_image(image, self.num_channels)


class MatchBoxes(Processor):
    """Match prior boxes with ground truth boxes.

    # Arguments
        prior_boxes: Numpy array of shape (num_boxes, 4).
        iou: Float in [0, 1]. Intersection over union in which prior boxes
            will be considered positive. A positive box is box with a class
            different than `background`.
        variance: List of two floats.
    """
    def __init__(self, prior_boxes, iou=.5):
        self.prior_boxes = prior_boxes
        self.iou = iou
        super(MatchBoxes, self).__init__()

    def call(self, boxes):
        boxes = match(boxes, self.prior_boxes, self.iou)
        return boxes
