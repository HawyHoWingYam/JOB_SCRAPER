import torch.nn as nn

# First convolutional layer block
conv_layer1 = nn.Sequential(
    nn.Conv2d(in_channels=1, out_channels=16, kernel_size=(5,5)),
    nn.ReLU(),
    nn.MaxPool2d(kernel_size=(2,2))
)

# Second convolutional layer block
conv_layer2 = nn.Sequential(
    nn.Conv2d(in_channels=16, out_channels=32, kernel_size=(3,3)),
    nn.ReLU(),
    nn.MaxPool2d(kernel_size=(2,2))
)

# Third convolutional layer block
conv_layer3 = nn.Sequential(
    nn.Conv2d(in_channels=32, out_channels=16, kernel_size=(1,1)),
    nn.ReLU(),
)

# First fully connected layer
fc_layer1 = nn.Sequential(
    nn.Linear(in_features=400, out_features=64),
    nn.ReLU(),
)

# Second fully connected layer (output layer)
fc_layer2 = nn.Linear(in_features=64, out_features=10)

# Combine all layers
CNN = nn.Sequential(
    conv_layer1,
    conv_layer2,
    conv_layer3,
    nn.Flatten(),
    fc_layer1,
    fc_layer2
)