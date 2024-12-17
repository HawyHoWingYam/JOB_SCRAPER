import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
from torchvision import transforms
from tqdm import tqdm
from torch.utils.data import DataLoader
from dataset import load_mnist, load_cifar10, load_fashion_mnist, imshow
from model import CNN


# test
@torch.no_grad()
def accuracy(model, data_loader):
    model.eval()
    correct, total = 0, 0
    for batch in data_loader:
        images, labels = batch
        images = images.to(device)
        labels = labels.to(device)

        outputs = model(images)
        _, predicted = torch.max(outputs.data, 1)
        total += labels.size(0)
        correct += (predicted == labels).sum().item()
    return correct / total


if torch.cuda.is_available():
    device = torch.device('cuda:0')
else:
    device = torch.device('cpu')


trainset, testset = load_mnist()

# 1.2.2d Hyperparameters
learning_rate = 0.001
num_epochs = 10
dataset_size = len(trainset)  # 60,000 for MNIST
desired_batches = 1000
batch_size = dataset_size // desired_batches 
milestones = [5,10]  # Reduce LR after 10 epochs
gamma = 0.01

# 1.2.2d
trainloader = DataLoader(trainset, batch_size=batch_size, shuffle=True)
testloader = DataLoader(testset, batch_size=batch_size, shuffle=False)

# Use CNN model instead of LeNet5
model = CNN.to(device)

loss_fn = nn.CrossEntropyLoss()
# optim.SGD(model.parameters(), lr=0.001, momentum=0.9) # 1.2.2b Adam optimizer
optimizer = optim.Adam(model.parameters(), lr=learning_rate)

# 1.2.2c
scheduler = optim.lr_scheduler.MultiStepLR(
    optimizer, milestones=milestones, gamma=gamma)

# 1.2.2d Training loop over the dataset multiple times
best_test_acc = 0.0
model.train()
# Add progress bar for epochs
for epoch in tqdm(range(num_epochs), desc='Epochs'):
    running_loss = 0.0
    # Add progress bar for batches
    pbar = tqdm(trainloader, desc=f'Epoch {epoch+1}', leave=False)
    for i, batch in enumerate(pbar, 0):
        images, labels = batch
        images = images.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()
        outputs = model(images)
        loss = loss_fn(outputs, labels)
        loss.backward()
        optimizer.step()

        running_loss += loss.item()
        # Update progress bar description with current loss
        pbar.set_description(f'Epoch {epoch+1}, Loss: {loss.item():.3f}')

        if (i + 1) % desired_batches == 0:
            print('\n[epoch %2d, batch %5d] loss: %.3f' %
                  (epoch + 1, i + 1, running_loss / desired_batches))
            running_loss = 0.0
            
            train_acc = accuracy(model, trainloader)
            test_acc = accuracy(model, testloader)
            current_lr = scheduler.get_last_lr()[0]
            print('Accuracy on the train set: %f %%' % (100 * train_acc))
            print('Accuracy on the test set: %f %%' % (100 * test_acc))
            print('The current learning rate is: %f ' %
                  (scheduler.get_last_lr()[0]))
            
            if test_acc > best_test_acc:
                best_test_acc = test_acc
                torch.save(model.state_dict(), 'model.pth')
                print(f'New best model saved with test accuracy: {100 * best_test_acc:.2f}%\n')

    scheduler.step()


model_file = 'model.pth'
torch.save(model.state_dict(), model_file)
print(f'Model saved to {model_file}.')

print('Finished Training')


# show some prediction result
dataiter = iter(testloader)
# images, labels = dataiter.next()
images, labels = next(dataiter)
images = images.to(device)
predictions = model(images).argmax(1).detach().cpu()

classes = trainset.classes
print('GroundTruth: ', ' '.join('%5s' % classes[i] for i in labels))
print('Prediction: ', ' '.join('%5s' % classes[i] for i in predictions))
imshow(torchvision.utils.make_grid(images.cpu()))


# 1.2.2d Accuracy
train_acc = accuracy(model, trainloader)
test_acc = accuracy(model, testloader)

print('Accuracy on the train set: %f %%' % (100 * train_acc))
print('Accuracy on the test set: %f %%' % (100 * test_acc))
