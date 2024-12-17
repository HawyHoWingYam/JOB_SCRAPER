import torch
import torch.nn as nn
import torch.optim as optim

import torchvision
import torchvision.transforms as transforms

from torch.utils.data import DataLoader
from dataset import load_fashion_mnist

if torch.cuda.is_available():
    device = torch.device(0)
else:
    device = torch.device('cpu')

trainset, testset = load_fashion_mnist()
trainloader = DataLoader(trainset, batch_size=32, shuffle=True)
testloader = DataLoader(testset, batch_size=32, shuffle=False)


## your code here
# TODO: load ResNet18 from PyTorch Hub, and train it to achieve 90+% classification accuracy on Fashion-MNIST.




## test
@torch.no_grad()
def accuracy(model, data_loader):
    model.eval()
    correct, total = 0, 0
    for batch in data_loader:
        images, labels = batch
        images = preprocess(images)
        images = images.to(device)
        labels = labels.to(device)

        outputs = model(images)
        _, predicted = torch.max(outputs.data, 1)
        total += labels.size(0)
        correct += (predicted == labels).sum().item()
    return correct / total

train_acc = accuracy(model, trainloader)
test_acc = accuracy(model, testloader)

print('Accuracy on the train set: %f %%' % (100 * train_acc))
print('Accuracy on the test set: %f %%' % (100 * test_acc))
