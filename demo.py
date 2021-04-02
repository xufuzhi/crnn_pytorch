import torch
import utils
import dataset
from PIL import Image
import cv2 as cv
import time

import models.crnn as crnn


model_path = './weights/netCRNN_last.pth'
# model_path = './data/crnn.pth'
img_path = './data/3.jpg'
# alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'
alphabet = '0123456789abcdefghijklmnopqrstuvwxyz-,\'\\(/!.$#:) @&%?=[];+'

# model = crnn.CRNN(32, 1, 37, 256)
model = crnn.CRNN(32, 1, 59, 256)
if torch.cuda.is_available():
    model = model.cuda()
print('loading pretrained model from %s' % model_path)
model.load_state_dict(torch.load(model_path))

converter = utils.StrLabelConverter(alphabet)

transformer = dataset.ResizeNormalize((100, 32))
image = Image.open(img_path).convert('L')
image = transformer(image)
if torch.cuda.is_available():
    image = image.cuda()
image = image.view(1, *image.size())

############################## debug
# image = image.repeat(1, 1, 1, 4)
# image = (image > 0.6) / 1.0
aa = image[0, ...].cpu().permute(1, 2, 0).numpy()
# cv.imshow('img', aa), cv.waitKeyEx(), cv.destroyAllWindows()

#####################

model.eval()
preds = model(image)

torch.cuda.synchronize()
t1 = time.time()
preds = model(image)
torch.cuda.synchronize()
print('time: ', time.time() - t1)

_, preds = preds.max(2)
preds = preds.transpose(1, 0).contiguous().view(-1)

preds_size = torch.IntTensor([preds.size(0)])
raw_pred = converter.decode(preds, preds_size, raw=True)
sim_pred = converter.decode(preds, preds_size, raw=False)
print('%-20s => %-20s' % (raw_pred, sim_pred))
