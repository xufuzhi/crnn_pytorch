import argparse
import time

import torch
import torch.backends.cudnn as cudnn
import torch.optim as optim
import torch.utils.data
from torch.nn import CTCLoss
import os
from utils import utils, dataset

import models.crnn as crnn
import eval


cudnn.benchmark = True

# random.seed(opt.manualSeed)
# np.random.seed(opt.manualSeed)
# torch.manual_seed(opt.manualSeed)


# custom weights initialization called on net_crnn
def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        m.weight.data.normal_(0.0, 0.02)
    elif classname.find('BatchNorm') != -1:
        m.weight.data.normal_(1.0, 0.02)
        m.bias.data.fill_(0)


def trainBatch(net, criterion, optimizer, data, iter_num):
    cpu_images, cpu_texts = data
    batch_size = cpu_images.size(0)
    utils.loadData(image, cpu_images)
    t, l = str2label.encode(cpu_texts)
    utils.loadData(text, t)
    utils.loadData(length, l)

    preds = net(image)
    preds_size = torch.LongTensor([preds.size(0)] * batch_size)
    cost = criterion(preds, text, preds_size, length) #/ batch_size
    optimizer.zero_grad()
    cost.backward()
    optimizer.step()

    # ### 计算这个批次精度
    if iter_num % opt.displayInterval == 0:
        aa = torch.ones(1).detach
        preds_v = preds.detach()
        preds_size_v = preds_size.detach()

        _, preds_v = preds_v.max(2)
        # preds = preds.squeeze(2)
        preds_v = preds_v.transpose(1, 0).contiguous().view(-1)
        sim_preds = str2label.decode(preds_v.data, preds_size_v.data, raw=False)
        n_correct = 0
        for pred, target in zip(sim_preds, cpu_texts):
            if pred == target.lower():
                n_correct += 1
        accuracy = n_correct / float(opt.batchSize)
        print(f'acc: {accuracy}')

    return cost


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--trainroot', required=True, help='path to dataset')
    parser.add_argument('--valroot', required=True, help='path to dataset')
    parser.add_argument('--workers', type=int, help='number of data loading workers', default=0)
    parser.add_argument('--batchSize', type=int, default=256, help='input batch size')
    parser.add_argument('--imgH', type=int, default=32, help='the height of the input image to network')
    parser.add_argument('--imgW', type=int, default=100, help='the width of the input image to network')
    parser.add_argument('--nh', type=int, default=256, help='size of the lstm hidden state')
    parser.add_argument('--nepoch', type=int, default=600, help='number of epochs to train for')
    # TODO(meijieru): epoch -> iter
    parser.add_argument('--cuda', action='store_true', help='enables cuda')
    parser.add_argument('--ngpu', type=int, default=1, help='number of GPUs to use')
    parser.add_argument('--pretrained', default='./weights/chinese/netCRNN_lastest.pth', help="path to pretrained model (to continue training)")
    parser.add_argument('--alphabet', type=str, default='./data/en.alphabet')
    parser.add_argument('--expr_dir', default='weights/chinese', help='Where to store samples and models')
    parser.add_argument('--displayInterval', type=int, default=500, help='Interval to be displayed')
    parser.add_argument('--n_test_disp', type=int, default=50, help='Number of samples to display when test')
    parser.add_argument('--valInterval', type=int, default=5000, help='Interval to be verifyed')
    parser.add_argument('--saveInterval', type=int, default=20000, help='Interval to be saved')
    parser.add_argument('--lr', type=float, default=0.0000002, help='learning rate for Critic, not used by adadealta')
    parser.add_argument('--beta1', type=float, default=0.5, help='beta1 for adam. default=0.5')
    parser.add_argument('--adam', action='store_true', help='Whether to use adam (default is rmsprop)')
    parser.add_argument('--adadelta', action='store_true', help='Whether to use adadelta (default is rmsprop)')
    parser.add_argument('--keep_ratio', action='store_true', help='whether to keep ratio for image resize')
    parser.add_argument('--manualSeed', type=int, default=1234, help='reproduce experiemnt')
    parser.add_argument('--random_sample', action='store_true',
                        help='whether to sample the dataset with random sampler')
    opt = parser.parse_args()
    print(opt)

    if not os.path.exists(opt.expr_dir):
        os.makedirs(opt.expr_dir)

    if torch.cuda.is_available() and not opt.cuda:
        print("WARNING: You have a CUDA device, so you should probably run with --cuda")

    # 读取字母表
    with open(opt.alphabet, encoding='utf-8') as f:
        alphabet = f.read().strip()

    # ### 构建数据集对象
    dataset_train = dataset.Dataset_lmdb(root=opt.trainroot)
    assert dataset_train
    if not opt.random_sample:
        sampler = dataset.RandomSequentialSampler(dataset_train, opt.batchSize)
    else:
        sampler = None
    train_loader = torch.utils.data.DataLoader(
        dataset_train, batch_size=opt.batchSize,
        shuffle=True, sampler=sampler,
        num_workers=int(opt.workers),
        collate_fn=dataset.AlignCollate(imgH=opt.imgH, imgW=opt.imgW, keep_ratio=opt.keep_ratio))
    dataset_val = dataset.Dataset_lmdb(root=opt.valroot, transform=dataset.ResizeNormalize((100, 32)))

    # 构建网络
    net_crnn = crnn.CRNN(opt.imgH, 1, len(alphabet) + 1, opt.nh)
    net_crnn.apply(weights_init)
    if opt.pretrained != '':
        print('loading pretrained model from %s' % opt.pretrained)
        net_crnn.load_state_dict(torch.load(opt.pretrained))
    print(net_crnn)

    str2label = utils.StrLabelConverter(alphabet)
    ctc_loss = CTCLoss(zero_infinity=True)
    # setup optimizer
    if opt.adam:
        optimizer = optim.Adam(net_crnn.parameters(), lr=opt.lr, betas=(opt.beta1, 0.999))
    elif opt.adadelta:
        optimizer = optim.Adadelta(net_crnn.parameters())
    else:
        optimizer = optim.RMSprop(net_crnn.parameters(), lr=opt.lr)

    image = torch.empty((opt.batchSize, 3, opt.imgH, opt.imgH), dtype=torch.float32)
    text = torch.empty(opt.batchSize * 5, dtype=torch.int32)
    length = torch.empty(opt.batchSize, dtype=torch.int32)

    if opt.cuda:
        net_crnn.cuda()
        # net_crnn = torch.nn.DataParallel(net_crnn, device_ids=range(opt.ngpu))
        image = image.cuda()
        ctc_loss = ctc_loss.cuda()

    # loss Averager
    loss_avg = utils.Averager()
    # ### begin training
    total_iter = len(train_loader) * opt.nepoch
    iteration = 0
    for epoch in range(opt.nepoch):
        for i, data in enumerate(train_loader, start=1):
            iteration += 1
            for p in net_crnn.parameters():
                p.requires_grad = True
            net_crnn.train()

            cost = trainBatch(net_crnn, ctc_loss, optimizer, data, iteration)
            loss_avg.add(cost)

            # ### 打印信息
            if iteration % opt.displayInterval == 0:
                print(f'epoch: [{epoch}/{opt.nepoch}] | iter: {iteration} | Loss: {loss_avg.val()}')
                loss_avg.reset()

            # ### 验证精度
            if iteration % opt.valInterval == 0:
                eval.val(net_crnn, dataset_val, ctc_loss, str2label, batchSize=256, max_iter=100)


            # ### 保存权重
            if iteration % opt.saveInterval == 0:
                torch.save(net_crnn.state_dict(), f'{opt.expr_dir}/netCRNN_{epoch}_{iteration}.pth')
            # 每2000次保存一次 lastest.pth
            if iteration % 2000 == 0:
                torch.save(net_crnn.state_dict(), f'{opt.expr_dir}/netCRNN_lastest.pth')

    torch.save(net_crnn.state_dict(), os.path.join(opt.expr_dir, 'netCRNN_last.pth'))
