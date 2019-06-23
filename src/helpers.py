import os
import pickle

import cv2
import matplotlib.pyplot as plt
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from config import CONFIG
from ml.autoencoder import Autoencoder
from ml.classifier import Classifier
from video_processing.video_data import VideoData


def get_latent_space_loaders(img_size=32, batch_size=32):
    """
    Return the latent space representation of the data
    :param img_size: pixels in width of the image
    :param batch_size: batch size for the dataloader
    :return: number of classes, train_loader, val_loader, test_loader
    """

    all_data, all_labels = load_video_data_labels(matrix_size=img_size)

    n_classes = len(np.unique(all_labels))
    autoencoder = Autoencoder(all_data.shape[1] * all_data.shape[2])
    autoencoder.load_state()
    torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # autoencoder = train_autoencoder()
    # print("Model trained")

    latent_space = []
    for pos, image in enumerate(all_data):
        latent_space.append(autoencoder.get_latent_space(torch.from_numpy(image.reshape(-1))).data.numpy())

    target = np.array(all_labels)
    latent_space = np.array(latent_space)

    _, train_loader, val_loader, test_loader = get_loaders(img_size, batch_size,
                                                           all_data=latent_space, all_labels=target)

    return n_classes, train_loader, val_loader, test_loader


def to_img(x):
    # x = 0.5 * (x + 1)
    # x = x.clamp(0, 1)
    x = x.view(x.size(0), 1, 22, 32)
    # x = x.view(x.size(0), 1, 28, 28)
    return x


def validate_autoencoder(model, loss_function, val_loader):
    test_loss = []
    model.eval()
    with torch.no_grad():
        for data in val_loader:
            img, _ = data
            img = img.view(img.size(0), -1)
            img = torch.autograd.Variable(img).cuda()
            # ===================forward=====================
            output = model(img)
            loss = loss_function(output, img)
            test_loss.append(loss.item())

    model.train()
    return np.average(test_loss)


def validate_classifier(model, loss_function, val_loader):
    test_loss = []
    model.eval()
    with torch.no_grad():
        for inputs, labels in val_loader:
            # 1. forward propagation
            output = model(inputs)
            # 2. loss calculation
            loss = loss_function(output, labels.type(torch.LongTensor))
            test_loss.append(loss.item())

    model.train()
    return np.average(test_loss)


def get_loaders(img_size=CONFIG["matrix_size"], batch_size=CONFIG["batch_size"],
                used_keypoints=CONFIG["used_keypoints"], interpolation_frames=CONFIG["interpolation_frames"],
                noise_frames=CONFIG["noise_frames"], all_data=None, all_labels=None):
    """ Return the train, validation and test loaders along with all the data in a dictionary """

    if all_data is None or all_labels is None:
        all_data, all_labels = load_video_data_labels(interpolation_frames, noise_frames, used_keypoints, img_size)

    p = np.random.permutation(len(all_data))
    train_len = int(len(p) / 80)
    others_len = int((len(p) - train_len) / 2)

    train_data, train_labels = all_data[p[:train_len]], all_labels[p[:train_len]]
    val_data = all_data[p[train_len:train_len + others_len]]
    val_labels = all_labels[p[train_len:train_len + others_len]]
    test_data, test_labels = all_data[p[-others_len:]], all_labels[p[-others_len:]]

    # Transform to tensor
    train_data_tensor, train_labels_tensor = torch.from_numpy(train_data), torch.from_numpy(train_labels)
    val_data_tensor, val_labels_tensor = torch.from_numpy(val_data), torch.from_numpy(val_labels)
    test_data_tensor, test_labels_tensor = torch.from_numpy(test_data), torch.from_numpy(test_labels)

    # Data Loader for easy mini-batch return in training, load the Dataset from the numpy arrays
    train_loader = DataLoader(TensorDataset(train_data_tensor, train_labels_tensor), batch_size=batch_size)
    val_loader = DataLoader(TensorDataset(val_data_tensor, val_labels_tensor), batch_size=batch_size)
    test_loader = DataLoader(TensorDataset(test_data_tensor, test_labels_tensor), batch_size=batch_size)

    data = {"train_data": train_data,
            "train_labels": train_labels,
            "val_data": val_data,
            "val_labels": val_labels,
            "test_data": test_data,
            "test_labels": test_labels,
            "all_data": all_data[p],
            "all_labels": all_labels[p]}

    return data, train_loader, val_loader, test_loader


def train_autoencoder(img_size=CONFIG["matrix_size"], batch_size=CONFIG["batch_size"], num_epochs=CONFIG["num_epochs"],
                      used_keypoints=CONFIG["used_keypoints"]):
    from torchvision.utils import save_image
    from torch import nn

    _, train_loader, val_loader, _ = get_loaders(img_size, batch_size, used_keypoints)
    learning_rate = CONFIG["learning_rate"]
    autoencoder = Autoencoder(train_loader.dataset[0][0].shape[0] * train_loader.dataset[0][0].shape[1]).cuda()
    loss_function = nn.MSELoss()
    optimizer = torch.optim.Adam(
        autoencoder.parameters(), lr=learning_rate, weight_decay=CONFIG["weight_decay"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f'Start training Autoencoder with {device}')
    train_loss = []
    val_loss = []
    for epoch in range(num_epochs):
        train_loss_help = []
        for data in train_loader:
            img, _ = data
            img = img.view(img.size(0), -1)
            img = torch.autograd.Variable(img).cuda()
            # ===================forward=====================
            output = autoencoder(img)
            loss = loss_function(output, img)
            train_loss_help.append(loss.item())
            # ===================backward====================
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        # ===================log========================
        epoch_train_loss = np.average(train_loss_help)
        epoch_val_loss = np.average(validate_autoencoder(autoencoder, loss_function, val_loader))
        train_loss.append(epoch_train_loss)
        val_loss.append(epoch_val_loss)
        print('epoch [{}/{}], train loss:{:.4f}, validation loss:{:.4f}'
              .format(epoch + 1, num_epochs, epoch_train_loss, epoch_val_loss))
        if epoch % 5 == 0:
            pic = to_img(output.cpu().data)
            save_image(pic, os.path.join(CONFIG["autoencoder_img_path"], 'image_{}_output.png'.format(epoch)))

            input_pic = to_img(img.cpu().data)
            save_image(input_pic, os.path.join(CONFIG["autoencoder_img_path"], 'image_{}_input.png'.format(epoch)))

    autoencoder.save_state()
    plt.plot(train_loss, label="Train loss")
    plt.plot(val_loss, label="Validation loss")
    plt.legend()
    plt.title("Loss history")
    plt.xlabel("Epochs")
    plt.ylabel("Loss")
    plt.show()

    return autoencoder


def train_classifier():
    batch_size = 32
    # Load data
    n_classes, train_loader, val_loader, _ = get_latent_space_loaders(batch_size=batch_size)

    learning_rate = 0.001
    classifier = Classifier(4)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f'Start training Classifier with {device}')

    epochs = 500
    loss_function = nn.CrossEntropyLoss()
    # optimizer = optim.SGD(classifier.parameters(), lr=learning_rate, weight_decay=1e-6, momentum=0.9, nesterov=True)
    optimizer = torch.optim.Adam(
        classifier.parameters(), lr=learning_rate, weight_decay=1e-5)
    train_loss, val_loss = [], []
    for epoch in range(epochs):  # loop over the dataset multiple times
        loss_history = []
        for inputs, labels in train_loader:
            # 1. forward propagation
            output = classifier(inputs)

            # 2. loss calculation
            loss = loss_function(output, labels.type(torch.LongTensor))

            # 3. backward propagation
            loss.backward()

            # 4. weight optimization
            optimizer.step()

            loss_history.append(loss.item())

        epoch_train_loss = np.average(loss_history)
        train_loss.append(epoch_train_loss)
        epoch_val_loss = np.average(validate_classifier(classifier, loss_function, val_loader))
        val_loss.append(epoch_val_loss)
        print('epoch [{}/{}], train loss:{:.4f}, validation loss:{:.4f}'
              .format(epoch + 1, epochs, epoch_train_loss, epoch_val_loss))

    plt.plot(train_loss, label="Train loss")
    plt.plot(val_loss, label="Validation loss")
    plt.legend()
    plt.title("Loss history")
    plt.xlabel("Epochs")
    plt.ylabel("Loss")
    plt.show()
    classifier.save_state()
    print('Finished Training')

    return classifier


def create_video_data_labels(interpolation_frames=CONFIG["interpolation_frames"],
                             noise_parameters=CONFIG["noise_frames"], used_keypoints=CONFIG["used_keypoints"],
                             matrix_size=CONFIG["matrix_size"], use_dilation=CONFIG["use_dilation"],
                             kernel_size=CONFIG["kernel_size"]):
    """
    Load the xmls files and create images using interpolation and the labels assigned to each of the images.

    :param interpolation_frames: Number of frames to use for the interpolations
    :param noise_parameters: Number of frames that are considered to be noise
    :param used_keypoints: keypoints to use when loading the frames
    :param matrix_size: Size of the images returned
    :param use_dilation: Flag to use dilation on the images
    :param kernel_size: Size of the kernel for the dilation
    :return: video data and labels
    """
    xml_folder = os.path.dirname(os.path.realpath(__file__)).split("src")[0].replace("\\", "/") + CONFIG[
        "xml_files_path"]
    data = []
    labels = []
    min_data = 99
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    for label, folder in enumerate(os.listdir(xml_folder)):
        for file in os.listdir(xml_folder + '/' + folder):
            file_path = xml_folder + '/' + folder + '/' + file
            video_data = VideoData(interpolations_frames=interpolation_frames, matrix_size=matrix_size,
                                   used_keypoints=used_keypoints, noise_frames=noise_parameters)
            video_data.load_xml_file(file_path)
            matrix = video_data.get_matrices()
            for frame in matrix:

                # Apply dilation if enabled.
                if use_dilation:
                    data.append(cv2.dilate(frame, kernel, iterations=1))
                else:
                    data.append(frame)

                labels.append(label)
            if matrix.shape[0] < min_data:
                min_data = matrix.shape[0]

        print(folder, "folder done. Label =", label)

    # Uncomment if a new class with noise white images is desired
    # white_image = np.ones((matrix_size - CONFIG["matrix_vertical_crop"], matrix_size))
    # for i in range(6000):
    #     noise = abs(np.random.normal(0, 0.1, white_image.shape))
    #     new_image = white_image - noise
    #     data.append(np.float32(new_image))
    #     labels.append(4)

    print("Smallest matrix size is", min_data)
    return np.array(data), np.array(labels)


def load_video_data_labels(interpolation_frames=CONFIG["interpolation_frames"], noise_parameters=CONFIG["noise_frames"],
                           used_keypoints=CONFIG["used_keypoints"], matrix_size=CONFIG["matrix_size"]):
    """
    Load the images and if they are not saved as pickle files then call the function to create them
    :param interpolation_frames: Number of frames to use for the interpolations
    :param noise_parameters: Number of frames that are considered to be noise
    :param used_keypoints: keypoints to use when loading the frames
    :param matrix_size: Size of the images returned
    :return: video data and labels
    """
    path = 'interpolation_' + str(interpolation_frames) + '_noise_' + str(
        noise_parameters) + '_matrix_size_' + str(matrix_size) + '.pkl'

    video_data_path = os.path.dirname(os.path.realpath(__file__)).split("src")[0].replace("\\",
                                                                                          "/") + "video_data_models/"
    try:
        with open(video_data_path + 'data_' + path, 'rb') as model:
            video_data = pickle.load(model)

        with open(video_data_path + 'labels_' + path, 'rb') as model:
            video_labels = pickle.load(model)

        print("Video data and labels loaded from file")

    except:
        print("Failed to load video data or labels, create it")
        video_data, video_labels = create_video_data_labels(interpolation_frames, noise_parameters, used_keypoints,
                                                            matrix_size)
        with open(video_data_path + 'data_' + path, 'wb') as output:
            pickle.dump(video_data, output)
        with open(video_data_path + 'labels_' + path, 'wb') as output:
            pickle.dump(video_labels, output)

        print("Video data and labels created and saved")

    return video_data, video_labels


#
# train_data, train_labels = load_video_data_labels(8,2)
# p = np.random.permutation(len(train_data))
# train_data, train_labels = train_data[p], train_labels[p]
# import matplotlib.pyplot as plt
#
# for i in p[:100]:
#     plt.imshow(train_data[i], cmap='gray')
#     plt.title("Label = " + str(train_labels[i]))
#     plt.show()

# train_autoencoder()
# train_classifier()
