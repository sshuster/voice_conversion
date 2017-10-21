import torch
from torch import optim
from torch.autograd import Variable
import numpy as np
import pickle
from model import Encoder
from model import Discriminator
from utils import Hps
from utils import DataLoader
from utils import Logger

class Solver(object):
    def __init__(self, hps, data_loader, log_dir='./log/'):
        self.hps = hps
        self.data_loader = data_loader
        self.Encoder_s = None
        self.Encoder_c = None
        self.Decoder = None
        self.Discriminator = None
        self.G_opt = None
        self.C_opt = None
        self.build_model()
        self.logger = Logger(log_dir)
        self.model_kept = []
        self.max_keep = 10

    def build_model(self):
        self.Encoder_s = Encoder(1, 1)
        self.Encoder_c = Encoder(1, 1)
        self.Decoder = Encoder(2, 1)
        self.Discriminator = Discriminator(2)
        if torch.cuda.is_available():
            self.Encoder_s.cuda()
            self.Encoder_c.cuda()
            self.Decoder.cuda()
            self.Discriminator.cuda()
        params = list(self.Encoder_s.parameters()) \
            + list(self.Encoder_c.parameters())\
            + list(self.Decoder.parameters()) 
        self.G_opt = optim.Adam(params, lr=self.hps.lr)
        self.C_opt = optim.Adam(self.Discriminator.parameters(), lr=self.hps.lr)

    def to_var(self, x):
        x = Variable(torch.from_numpy(x), requires_grad=True)
        if torch.cuda.is_available():
           return x.cuda()
        else:
            return x

    def save_model(self, model_path, iteration):
        Es_path = os.path.join(model_path, 'Es-{}.pkl'.format(iteration))
        Ec_path = os.path.join(model_path, 'Ec-{}.pkl'.format(iteration))
        Dec_path = os.path.join(model_path, 'Dec-{}.pkl'.format(iteration))
        Dis_path = os.path.join(model_path, 'Dis-{}.pkl'.format(iteration))
        torch.save(self.Encoder_s.state_dict(), Es_path)
        torch.save(self.Encoder_c.state_dict(), Ec_path)
        torch.save(self.Decoder.state_dict(), Dec_path)
        torch.save(self.Discriminator.state_dict(), Dis_path)
        self.model_kept.append([Es_path, Ec_path, Dec_path, Dis_path])
        if len(self.model_kept) >= self.max_keep:
            for model_path in self.model_kept[0]:
                os.remove(model_path)
            self.model_kept.pop(0)

    def train(self, model_path):
        for iteration in range(self.hps.iterations):
            print(iteration)
            X_i_t, X_i_tk, X_j = [self.to_var(x) for x in next(self.data_loader)]
            # encode
            Ec_i_t, Ec_i_tk, Ec_j = self.Encoder_c(X_i_t), self.Encoder_c(X_i_tk), self.Encoder_c(X_j)
            Ec_same = torch.cat([Ec_i_t, Ec_i_tk], dim=1)
            Ec_diff = torch.cat([Ec_i_t, Ec_j], dim=1)
            # train discriminator
            L_adv_C = -torch.mean(
                torch.log(self.Discriminator(Ec_i_t, Ec_i_tk)) + 
                torch.log(1 - self.Discriminator(Ec_i_t, Ec_j))
            )
            self.Discriminator.zero_grad()
            (self.hps.beta * L_adv).backward()
            # clipping
            torch.nn.utils.clip_grad_norm(self.Discriminator.parameters(), self.hps.max_grad_norm)
            self.d_opt.step()
            # train encoder and decoder
            Es_i_t = self.Encoder_s(X_i_t)
            Es_i_tk = self.Encoder_s(X_i_tk)
            Ec_i_t = self.Encoder_c(X_i_t)
            Ec_i_tk = self.Encoder_c(X_i_tk) 
            L_sim = torch.mean((Es_i_t - Es_i_tk) ** 2)
            E = torch.cat([Es_i_t, Ec_i_tk], dim=1)
            X_tilde = self.Decoder(E)
            L_rec = torch.mean((X_tilde - X_i_tk) ** 2)
            Ec_prob = self.Discriminator(Ec_i_t, Ec_i_tk)
            L_adv_E = -(0.5 * torch.log(Ec_prob) + 0.5 * torch.log(1 - Ec_prob))
            L = L_rec + self.hps.alpha * L_sim + self.hps.beta * L_adv_E
            self.Encoder_s.zero_grad()
            self.Encoder_c.zero_grad()
            self.Decoder.zero_grad()
            L.backward()
            # clipping
            params = list(self.Encoder_s.parameters()) \
                + list(self.Encoder_c.parameters())\
                + list(self.Decoder.parameters()) 
            torch.nn.utils.clip_grad_norm(
                params,
                self.hps.max_grad_norm
            )
            self.g_opt.step()
            # print info
            slot_value = {
                iteration,
                self.hps.iterations,
                L_rec.data[0],
                L_sim.data[0],
                L_adv_C.data[0],
                L_adv_E.data[0]
            }
            print(
                'iteration:[%06d/%06d], L_rec=%.2f, L_sim=%.2f,'
                'L_adv_C=%.2f, L_adv_E=%.2f\r' 
                % slot_value,
                end=''
            )
            info = {
                'L_rec':L_rec.data[0],
                'L_sim':L_sim.data[0],
                'L_adv_C':L_adv_C.data[0],
                'L_adv_E':L_adv_E.data[0],
            }
            for tag, value in info.items():
                self.logger.scalar_summary(tag, value, iteration + 1)

            if iteration % 100 == 0:
                self.save_model(model_path, iteration)

if __name__ == '__main__':
    hps = Hps()
    hps.load('./hps/v1.json')
    hps_tuple = hps.get_tuple()
    data_loader = DataLoader(
        '/storage/raw_feature/voice_conversion/libre_equal.h5',
        '/storage/raw_feature/voice_conversion/train-clean-100-speaker-sex.txt'
    )
    solver = Solver(hps_tuple, data_loader)
    solver.train()
