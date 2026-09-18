import torch
import torch.nn as nn
import os

import framework.port.network as network

class Adapter(network.Port, nn.Module):
    def __init__(self, **kwargs):
        #super().__init__()
        nn.Module.__init__(self)   # ✔️ inizializza PyTorch
        network.Port.__init__(self) 
        tipo = kwargs.get('tipo', 'linear')
        input = kwargs.get('input', 32)
        output = kwargs.get('output', 32)
        self.layers = nn.ModuleList()
        match tipo:
            case 'spiking':
                self.layers.append(nn.Parameter(input, requires_grad=False))
                self.layers.append(nn.Parameter(output, requires_grad=False))
            case 'linear':
                self.layers.append(nn.Linear(input, output))
            case _:
                raise ValueError(f"Tipo di rete non supportato: {tipo}")

    def compute(self, *args):
        # Implementazione della logica di calcolo della rete neurale
        # Questo è un esempio generico; dovresti adattarlo alle tue esigenze specifiche.
        input_sequence = args[0]  # Supponendo che il primo argomento sia la sequenza di input
        return self.forward(input_sequence)

    def forward(self, x):
        if self.tipo == 'linear':
            return self.forward_linear(x)
        elif self.tipo == 'spiking':
            return self.forward_spiking(x)

    def forward_linear(self, x):
        x_flat = x.flatten(start_dim=1)
        return self.layers[0](x_flat)

    def forward_spiking(self, input_sequence):
        batch_size, time_steps, _ = input_sequence.shape

        membrane = torch.zeros(batch_size, self.output_dim, device=input_sequence.device)
        spikes = torch.zeros_like(membrane)
        spike_history = []

        for t in range(time_steps):
            x_t = input_sequence[:, t, :]
            current = (
                torch.matmul(x_t, self.w_in.t()) +
                torch.matmul(spikes, self.w_rec.t())
            )

            membrane = membrane * self.leak_rate + current
            spikes = (membrane >= self.threshold).float()
            membrane = membrane * (1.0 - spikes)

            spike_history.append(spikes)

        return torch.stack(spike_history, dim=1)

    # -----------------------
    # TRAINING API
    # -----------------------
    def configure_training(self, lr=1e-3, loss_fn=None):
        self.optimizer = optim.Adam(self.parameters(), lr=lr)
        self.criterion = loss_fn if loss_fn is not None else nn.MSELoss()

    def training_step(self, x, y):
        if self.optimizer is None or self.criterion is None:
            raise RuntimeError("Chiama configure_training() prima del training")

        self.train()

        self.optimizer.zero_grad()

        pred = self.forward(x)
        loss = self.criterion(pred, y)

        loss.backward()
        self.optimizer.step()

        return loss.item()

    def fit(self, dataloader, epochs=10, verbose=True):
        history = []

        for epoch in range(epochs):
            total_loss = 0.0

            for x, y in dataloader:
                loss = self.training_step(x, y)
                total_loss += loss

            avg_loss = total_loss / len(dataloader)
            history.append(avg_loss)

            if verbose:
                print(f"[Epoch {epoch+1}/{epochs}] loss={avg_loss:.6f}")

        return history

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        checkpoint = {
            "model_state": self.state_dict(),
            "tipo": self.tipo,
            "input_dim": self.input_dim,
            "output_dim": self.output_dim,
        }

        # salvi anche parametri specifici per spiking
        if self.tipo == "spiking":
            checkpoint["threshold"] = self.threshold
            checkpoint["leak_rate"] = self.leak_rate

        torch.save(checkpoint, path)
        print(f"[SAVE] modello salvato in {path}")


    def load(self, path: str, device="cpu"):
        checkpoint = torch.load(path, map_location=device)

        # sicurezza: controlla compatibilità
        if checkpoint["tipo"] != self.tipo:
            raise ValueError("Tipo rete non compatibile con checkpoint")

        if checkpoint["input_dim"] != self.input_dim or checkpoint["output_dim"] != self.output_dim:
            raise ValueError("Dimensioni rete non compatibili")

        # aggiorna pesi
        self.load_state_dict(checkpoint["model_state"])

        # ripristina extra params
        if self.tipo == "spiking":
            self.threshold = checkpoint.get("threshold", self.threshold)
            self.leak_rate = checkpoint.get("leak_rate", self.leak_rate)

        print(f"[LOAD] pesi aggiornati da {path}")