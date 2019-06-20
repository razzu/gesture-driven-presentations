import torch
import numpy as np

from video_processing.load_data import load_video_data_labels
from ml.autoencoder_new import *
import os

def get_latent_space(img_size=32, batch_size=32):
    train_data, train_labels, dataloader = load_train_data(img_size, batch_size)

    autoencoder = Autoencoder(train_data.shape[1] * train_data.shape[2]).cuda()
    latent_space = autoencoder.get_latent_space(train_data)

    return latent_space


data = get_latent_space()
print("HELLO")