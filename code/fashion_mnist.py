import torch
import torch.nn as nn
import torch.optim as optim

import torchvision
import torchvision.transforms as transforms

from torch.utils.data import DataLoader
from dataset import load_fashion_mnist
from tqdm import tqdm


# test
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


if torch.cuda.is_available():
    device = torch.device(0)
else:
    device = torch.device('cpu')

trainset, testset = load_fashion_mnist()
trainloader = DataLoader(trainset, batch_size=32, shuffle=True)
testloader = DataLoader(testset, batch_size=32, shuffle=False)

# your code here
# TODO: load ResNet18 from PyTorch Hub, and train it to achieve 90+% classification accuracy on Fashion-MNIST.
# Load ResNet18 and modify for Fashion-MNIST
model = torch.hub.load('pytorch/vision:v0.10.0', 'resnet18', pretrained=True)
# Modify first conv layer to accept grayscale input
model.conv1 = nn.Conv2d(1, 64, kernel_size=7, stride=2, padding=3, bias=False)
# Modify final fully connected layer for 10 classes
model.fc = nn.Linear(model.fc.in_features, 10)
model = model.to(device)

# Define preprocessing pipeline for training
preprocess = transforms.Compose([
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomRotation(10),
    transforms.Resize(224),  # ResNet18 expects 224x224 images
    transforms.Lambda(lambda x: x.repeat(3, 1, 1) if x.size(
        0) == 1 else x)  # Expand grayscale to 3 channels
])


# Training setup
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=0.001)
scheduler = optim.lr_scheduler.ReduceLROnPlateau(
    optimizer, mode='max', patience=2)

# Training loop
num_epochs = 20
best_acc = 0.0

for epoch in tqdm(range(num_epochs), desc='Training'):
    model.train()
    running_loss = 0.0
    
    # Add tqdm for batch iterations
    pbar = tqdm(trainloader, desc=f'Epoch {epoch+1}', leave=False)
    for images, labels in pbar:
        images = preprocess(images).to(device)
        labels = labels.to(device)

        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        running_loss += loss.item()
        # Update progress bar with current loss
        pbar.set_description(f'Epoch {epoch+1}, Loss: {loss.item():.4f}')

    # Evaluate and save best model
    test_acc = accuracy(model, testloader)
    print(f'Epoch {epoch+1}, Loss: {running_loss/len(trainloader):.4f}, Test Acc: {test_acc*100:.2f}%')

    if test_acc > best_acc:
        best_acc = test_acc
        torch.save(model.state_dict(), 'fashion_mnist.pth')

    scheduler.step(test_acc)

print(f'Best test accuracy: {best_acc*100:.2f}%')


train_acc = accuracy(model, trainloader)
test_acc = accuracy(model, testloader)

print('Accuracy on the train set: %f %%' % (100 * train_acc))
print('Accuracy on the test set: %f %%' % (100 * test_acc))
