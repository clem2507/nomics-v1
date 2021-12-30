import os
import sys
import time
import statistics
import numpy as np

from math import sqrt
from tensorflow.keras.models import save_model
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix, accuracy_score

from tqdm import tqdm
from matplotlib import pyplot as plt
from tensorflow.keras import Sequential
from tensorflow.keras.layers import Conv1D, LSTM, Dropout, MaxPooling1D, Flatten, Dense, TimeDistributed

sys.path.append(os.path.dirname(os.path.abspath('util.py')) + '/training/data_loader')
sys.path.append(os.path.dirname(os.path.abspath('util.py')) + '/utils')

from preprocessing import Preprocessing
from util import plot_confusion_matrix, TimingCallback


def evaluate_model(analysis_directory, model_name, segmentation_value, downsampling_value, epochs, data_balancing, log_time, batch_size, standard_scale, stateful):
    """
    Method used to create and evaluate a deep learning model on data, either CNN or LSTM

    Parameters:

    -analysis_directory: directory path containing the analyses to create the dataframes
    -model_name: name of the model to train, either CNN or LSTM
    -segmentation_value: window segmentation value in minute
    -downsampling_value: signal downsampling value in second
    -epochs: number of epochs to train the model
    -data_balancing: true if balanced data is needed, false otherwise
    -log_time: save the time when the computation starts for the directory name
    -batch_size: batch size for training
    -standard_scale: true to perform a standardizatin by centering and scaling the data
    -stateful: true to use stateful LSTM instead of stateless

    Returns:

    -accuracy: model accuracy on the testing set
    """


    X_train, y_train, X_test, y_test = Preprocessing(analysis_directory=analysis_directory, segmentation_value=segmentation_value, downsampling_value=downsampling_value, data_balancing=data_balancing, log_time=log_time, standard_scale=standard_scale, stateful=stateful).create_dataset()

    model = Sequential()
    # Stateless model
    if not stateful:
        n_timesteps, n_features, n_outputs, validation_split, verbose = X_train.shape[1], X_train.shape[2], y_train.shape[1], 0.1, 1
        if model_name == 'cnn':
            # using 1Hz resolution and 1 minute window -- 60 sample size
            model.add(Conv1D(filters=16, kernel_size=5, strides=2, activation='relu', input_shape=(n_timesteps, n_features)))   # conv layer -- 1 -- Output size 16 x 29
            model.add(Conv1D(filters=32, kernel_size=3, strides=1, activation='relu'))    # conv layer -- 2 -- Output size 32 x 27
            model.add(MaxPooling1D(pool_size=2))   # max pooling -- 3 -- Output size 32 x 27
            model.add(Dropout(0.2))   # dropout -- 4 -- Output size 32 x 14
            model.add(Flatten())   # flatten layer -- 5 -- Output size 1 x 448
            model.add(Dense(64, activation='relu'))   # fully connected layer -- 6 -- Output size 1 x 64
            model.add(Dropout(0.2))   # dropout -- 7 -- Output size 1 x 64
            model.add(Dense(n_outputs, activation='sigmoid'))   # fully connected layer -- 8 -- Output size 1 x 2
            model.compile(loss='binary_crossentropy', optimizer='adam', metrics=['accuracy'])

        elif model_name == 'lstm':
            model.add(LSTM(64, input_shape=(n_timesteps, n_features)))   # lstm layer -- 1 -- Output size None x 64
            model.add(Dropout(0.2))   # dropout -- 2 -- Output size None x 64
            model.add(Dense(32, activation='relu'))   # fully connected layer -- 3 -- Output size None x 32
            model.add(Dropout(0.2))   # dropout -- 4 -- Output size None x 32
            model.add(Dense(n_outputs, activation='sigmoid'))   # fully connected layer -- 5 -- Output size None x 2
            model.compile(loss='binary_crossentropy', optimizer='adam', metrics=['accuracy'])

        print(model.summary())

        time_callback = TimingCallback()

        history = model.fit(X_train, y_train, validation_split=validation_split, epochs=epochs, batch_size=batch_size, verbose=verbose, callbacks=[time_callback])

        # metrics history epochs after epochs
        training_accuracy_history = history.history['accuracy']
        training_loss_history = history.history['loss']
        validation_accuracy_history = history.history['val_accuracy']
        validation_loss_history = history.history['val_loss']

        # evaluate model
        _, accuracy, *r = model.evaluate(X_test, y_test, batch_size=batch_size, verbose=verbose)

        predictions = model.predict(X_test)
        classes = np.argmax(predictions, axis=1)

        total_y_test = []    # predicted label list
        # loop that runs through the list of model predictions to keep the highest predicted probability values
        for item in y_test:
            total_y_test.append(np.argmax(item))
        y_test = total_y_test
    # Stateful model
    else:
        n_timesteps, n_features, n_outputs, validation_split, return_sequences = None, 1, 1, 0.1, True
        model.add(LSTM(20, batch_input_shape=(batch_size, n_timesteps, n_features), stateful=stateful, return_sequences=return_sequences))   # lstm layer -- 1 -- Output size None x 10
        model.add(Dropout(0.2))   # dropout -- 2 -- Output size None x 10
        model.add(TimeDistributed(Dense(n_outputs, activation='sigmoid')))   # fully connected layer -- 3 -- Output size None x 1
        model.compile(loss='binary_crossentropy', optimizer='adam', metrics=['accuracy'])

        print(model.summary())

        training_accuracy_history = []
        training_loss_history = []
        validation_accuracy_history = []
        validation_loss_history = []

        computation_time_history = []

        X_train, X_val, y_train, y_val = train_test_split(X_train, y_train, test_size=validation_split, random_state=42)

        print('Model train...')
        for epoch in range(epochs):
            print('----- EPOCH #{} -----'.format(epoch+1))
            print('---> Training')
            start = time.time()
            mean_tr_acc = []
            mean_tr_loss = []
            for i in tqdm(range(len(X_train))):
                for j in range(0, len(X_train[i]), batch_size):
                    if j+batch_size < len(X_train[i]):
                        tr_loss, tr_acc, *r = model.train_on_batch(np.reshape(X_train[i][j:j+batch_size], (batch_size, 1, 1)), np.reshape(y_train[i][j:j+batch_size], (batch_size, 1, 1)))
                        mean_tr_acc.append(tr_acc)
                        mean_tr_loss.append(tr_loss)
                model.reset_states()

            training_accuracy_history.append(np.mean(mean_tr_acc))
            training_loss_history.append(np.mean(mean_tr_loss))
            print('train accuracy = {}'.format(np.mean(mean_tr_acc)))
            print('train loss = {}'.format(np.mean(mean_tr_loss)))

            print('---> Validation')
            mean_val_acc = []
            mean_val_loss = []
            for i in tqdm(range(len(X_val))):
                for j in range(0, len(X_val[i]), batch_size):
                    if j+batch_size < len(X_val[i]):
                        te_loss, te_acc, *r = model.test_on_batch(np.reshape(X_val[i][j:j+batch_size], (batch_size, 1, 1)), np.reshape(y_val[i][j:j+batch_size], (batch_size, 1, 1)))
                        mean_val_acc.append(te_acc)
                        mean_val_loss.append(te_loss)
                model.reset_states()

            validation_accuracy_history.append(np.mean(mean_val_acc))
            validation_loss_history.append(np.mean(mean_val_loss))
            print('val accuracy = {}'.format(np.mean(mean_val_acc)))
            print('val loss = {}'.format(np.mean(mean_val_loss)))
            end = time.time()

            computation_time_history.append(end-start)

        print('---> Testing')
        mean_te_acc = []
        for i in tqdm(range(len(X_test))):
            classes = []
            for j in range(0, len(X_test[i]), batch_size):
                if j+batch_size < len(X_test[i]):
                    y_pred, *r = model.predict_on_batch(np.reshape(X_test[i][j:j+batch_size], (batch_size, 1, 1)))
                    for label in y_pred:
                        pred_label = round(label[0])
                        classes.append(pred_label)
            model.reset_states()
            mean_te_acc.append(accuracy_score(y_test, classes))

        accuracy = np.mean(mean_te_acc)

    # 95 % confidence interval computation
    interval = 1.96 * sqrt((accuracy * (1 - accuracy)) / len(X_test))

    # confustion matrix np array creation based on the prediction made by the model on the test data
    cm = confusion_matrix(y_true=y_test, y_pred=classes)

    # directory creation
    save_dir = os.path.dirname(os.path.abspath('util.py')) + f'/models/{model_name}/{log_time}'
    os.mkdir(save_dir)

    # summary txt file
    model_info_file = open(f'{save_dir}/info.txt', 'w')
    model_info_file.write(f'This file contains information about the {model_name} model \n')
    model_info_file.write('--- \n')
    if not stateful:
        model_info_file.write(f'Segmentation value = {segmentation_value} \n')
    else:
        model_info_file.write(f'Segmentation value = 0 \n')
    model_info_file.write(f'Downsampling value = {downsampling_value} \n')
    model_info_file.write(f'Signal frequency = {1/downsampling_value} Hz \n')
    model_info_file.write(f'Batch size = {batch_size} \n')
    model_info_file.write(f'Standard scale = {int(standard_scale)} \n')
    model_info_file.write(f'Stateful = {int(stateful)} \n')
    model_info_file.write(f'Data balancing = {int(data_balancing)} \n')
    model_info_file.write('--- \n')
    model_info_file.write(f'Log time = {log_time} \n')
    model_info_file.write('--- \n')
    model_info_file.write(f'Num of epochs = {epochs} \n')
    model_info_file.write(f'Epochs training computation time history (in sec) = {time_callback.logs} \n')
    model_info_file.write(f'Epochs training computation time mean (in sec) = {statistics.mean(time_callback.logs)} \n')
    model_info_file.write('--- \n')
    model_info_file.write(f'Training accuracy history = {training_accuracy_history} \n')
    model_info_file.write(f'Training loss history = {training_loss_history} \n')
    model_info_file.write('--- \n')
    model_info_file.write(f'Validation accuracy history = {validation_accuracy_history} \n')
    model_info_file.write(f'Validation loss history = {validation_loss_history} \n')
    model_info_file.write('--- \n')
    model_info_file.write(f'Radius of the CI = {interval} \n')
    model_info_file.write(f'True classification of the model is likely between {accuracy - interval} and {accuracy + interval} \n')
    model_info_file.write('--- \n')
    model_info_file.write(f'Test accuracy = {accuracy} \n')
    model_info_file.write(f'Confusion matrix (invalid | valid) = \n {cm} \n')
    model_info_file.write('--- \n')
    model_info_file.close()

    # confusion matrix plot
    labels = ['Invalid', 'Valid']
    cm_plt = plot_confusion_matrix(cm=cm, classes=labels, title='Confusion Matrix')

    cm_plt.savefig(f'{save_dir}/cm_plt.png', bbox_inches='tight')
    cm_plt.close()

    # chart with the learning curves creation
    figure, axes = plt.subplots(nrows=2, ncols=1)

    x = list(range(1, epochs + 1))

    axes[0].plot(x, training_accuracy_history, label='train acc')
    axes[0].plot(x, validation_accuracy_history, label='val acc')
    axes[0].set_title('Training and validation accuracy')
    axes[0].set_xlabel('epochs')
    axes[0].set_ylabel('accuracy')
    axes[0].legend(loc='best')
    axes[0].grid()

    axes[1].plot(x, training_loss_history, label='train loss')
    axes[1].plot(x, validation_loss_history, label='val loss')
    axes[1].set_title('Training and validation loss')
    axes[1].set_xlabel('epochs')
    axes[1].set_ylabel('loss')
    axes[1].legend(loc='best')
    axes[1].grid()

    figure.set_figheight(8)
    figure.set_figwidth(6)
    figure.tight_layout()
    # plot save
    figure.savefig(f'{save_dir}/metrics_plt.png', bbox_inches='tight')

    plt.close(fig=figure)

    # save of the model weights
    save_model(model, f'{save_dir}/saved_model')

    return accuracy


def train_model(analysis_directory, model, segmentation_value, downsampling_value, epochs, data_balancing, log_time, batch_size, standard_scale, stateful):
    """
    Callable method to start the training of the model

    Parameters:

    -analysis_directory: directory path containing the analyses to create the dataframes
    -model: name of the model to train, either CNN or LSTM
    -segmentation_value: window segmentation value in minute
    -downsampling_value: signal downsampling value in second
    -epochs: number of epochs to train the model
    -data_balancing: true if balanced data is needed, false otherwise
    -log_time: save the time when the computation starts for the directory name
    -batch_size: batch size for training
    -standard_scale: true to perform a standardizatin by centering and scaling the data
    -stateful: true to use stateful LSTM instead of stateless
    """

    segmentation_value = float(segmentation_value)
    downsampling_value = float(downsampling_value)
    score = evaluate_model(analysis_directory, model, segmentation_value, downsampling_value, epochs, data_balancing, log_time, batch_size, standard_scale, stateful)
    score = score * 100.0
    print('test accuracy:', score, '%')
    print('-----')
