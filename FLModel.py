# Federated Learning Model in PyTorch
import torch
from torch import nn
from torch.utils.data import Dataset, DataLoader, TensorDataset

import numpy as np
import copy
import random


class FLClient(nn.Module):
    """ Client of Federated Learning framework.
        1. Receive global model from server
        2. Perform local training (compute gradients)
        3. Return local model (gradients) to server
    """
    # TODO 1. split dataset into Non-iid
    #      2. - batch gradient descend (DONE)
    def __init__(self, model, output_size, data, lr, E, batch_size, device=None):
        """
        :param model: ML model's training process should be implemented
        :param data: (tuple) dataset, all data in client side is used as training data
        :param lr: learning rate
        :param E: epoch of local update
        """
        super(FLClient, self).__init__()
        self.device = device
        self.BATCH_SIZE = batch_size
        torch_dataset = TensorDataset(torch.tensor(data[0]),
                                      torch.tensor(data[1]))
        self.data_size = len(torch_dataset)
        self.data_loader = DataLoader(
            dataset=torch_dataset,
            batch_size=self.BATCH_SIZE,
            shuffle=True
        )

        self.lr = lr
        self.E = E
        self.model = model(data[0].shape[1], output_size).to(self.device)

    def recv(self, model_par):
        """receive global model from aggregator (server)"""
        self.model.load_state_dict(copy.deepcopy(model_par))

    def update(self):
        """local model update, compute gradients"""
        # criterion = nn.BCELoss()
        self.model.train()
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.SGD(self.model.parameters(), lr=self.lr, momentum=0.5)
        losses = []
        for e in range(self.E):
            for batch_x, batch_y in self.data_loader:
                batch_x, batch_y = batch_x.to(self.device), batch_y.to(self.device)

                pred_y = self.model(batch_x)
                loss = criterion(pred_y, batch_y.long())
                optimizer.zero_grad()
                loss.backward()
                losses += [loss.item()]
                optimizer.step()
            # print(np.mean(losses))
            losses = []


class FLServer(nn.Module):
    """ Server of Federated Learning
        1. Receive model (or gradients) from clients
        2. Aggregate local models (or gradients)
        3. Compute global model, broadcast global model to clients
    """
    def __init__(self, fl_par):
        super(FLServer, self).__init__()

        self.device = fl_par['device']
        self.client_num = fl_par['client_num']
        self.E = fl_par['tot_E']    # total epochs for global iteration
        self.C = fl_par['C']        # (float) C in [0, 1]
        self.data = torch.tensor(fl_par['data'][-1][0]).to(self.device)    # test set
        self.target = torch.tensor(fl_par['data'][-1][1]).to(self.device)  # target label
        self.input_size = int(self.data.shape[1])

        self.clients = [FLClient(fl_par['model'],
                                 fl_par['output_size'],
                                 fl_par['data'][i],
                                 fl_par['lr'],
                                 fl_par['E'],
                                 fl_par['batch_size'],
                                 self.device)
                        for i in range(self.client_num)]

        self.global_model = fl_par['model'](self.input_size, fl_par['output_size']).to(self.device)
        self.weight = np.array([client.data_size*1.0 for client in self.clients])
        # self.weight /= np.sum(self.weight)

    def aggregated(self, idxs_users):
        """FedAvg Algorithm"""
        model_par = [self.clients[idx].model.state_dict() for idx in idxs_users]
        new_par = model_par[0].copy()
        for name in new_par:
            new_par[name] = torch.zeros(new_par[name].shape).to(self.device)
        for client_id, par in enumerate(model_par):
            for name in new_par:
                new_par[name] += par[name] * (self.weight[client_id] / np.sum(self.weight[idxs_users]))
        # update global model (for testing accuracy on server side)
        self.global_model.load_state_dict(copy.deepcopy(new_par))
        return self.global_model.state_dict().copy()

    def broadcast(self, new_par):
        """Send aggregated model to all clients"""
        for client in self.clients:
            client.recv(new_par.copy())

    def test_acc(self):
        # compute accuracy using test set
        self.global_model.eval()
        t_pred_y = self.global_model(self.data)
        _, predicted = torch.max(t_pred_y, 1)

        acc = (predicted == self.target).sum().item() / self.target.size(0)
        # tar = set(np.where(self.target.cpu() == 1)[0])
        # tp = len(set(np.where(predicted.cpu() == 1)[0]) & tar) / len(tar)
        # t_pred_y = t_pred_y.flatten()
        # mask = (t_pred_y > 0.5)*1.0
        # acc = (mask == self.target).sum().item() / self.target.size(0)
        return acc

    def global_update(self):
        for e in range(self.E):
            idxs_users = np.random.choice(range(len(self.clients)), int(self.C * len(self.clients)), replace=False)
            for idx in idxs_users:
                self.clients[idx].update()
            self.broadcast(self.aggregated(idxs_users))
            acc = self.test_acc()
            print("global epochs = {:d}, acc = {:.4f}".format(e+1, acc))

