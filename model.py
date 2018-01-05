import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
from load import MAX_LENGTH
from utils import USE_CUDA


class Encoder(nn.Module):
    def __init__(self, input_size, hidden_size):
        super(Encoder, self).__init__()
        self.hidden_size = hidden_size
        self.RNN = nn.GRU(input_size, hidden_size, num_layers=2, bidirectional=True)

    def init_hidden(self, batch_size):
        hidden = Variable(torch.zeros(4, batch_size, self.hidden_size))
        if USE_CUDA:
            return hidden.cuda()
        else:
            return hidden

    def forward(self, input_seq, hidden):
        outputs, hidden = self.RNN(input_seq, hidden)  # output: ( batch,seq_len, hidden*n_dir)
        # outputs, output_lengths = torch.nn.utils.rnn.pad_packed_sequence(outputs,batch_first = True)
        return hidden


class Attn(nn.Module):
    def __init__(self, method, hidden_size, max_length=MAX_LENGTH):
        super(Attn, self).__init__()

        self.method = method
        self.hidden_size = hidden_size

        if self.method == 'general':
            self.attn = nn.Linear(self.hidden_size, hidden_size)

        elif self.method == 'concat':
            self.attn = nn.Linear(self.hidden_size * 2, hidden_size)
            self.other = nn.Parameter(torch.FloatTensor(1, hidden_size))

    def forward(self, hidden, encoder_outputs):
        seq_len = len(encoder_outputs)

        # Create variable to store attention energies
        attn_energies = Variable(torch.zeros(seq_len))  # B x 1 x S
        if USE_CUDA:
            attn_energies = attn_energies.cuda()

        # Calculate energies for each encoder output
        for i in range(seq_len):
            attn_energies[i] = self.score(hidden, encoder_outputs[i])

        # Normalize energies to weights in range 0 to 1, resize to 1 x 1 x seq_len
        return F.softmax(attn_energies).unsqueeze(0).unsqueeze(0)

    def score(self, hidden, encoder_output):

        if self.method == 'dot':
            energy = hidden.dot(encoder_output)
            return energy

        elif self.method == 'general':
            energy = self.attn(encoder_output)
            energy = hidden.dot(energy)
            return energy

        elif self.method == 'concat':
            energy = self.attn(torch.cat((hidden, encoder_output), 1))
            energy = self.other.dot(energy)
            return energy


class AttnDecoder(nn.Module):
    def __init__(self, attn_model, hidden_size, output_size):
        super(AttnDecoder, self).__init__()
        self.attn_model = attn_model
        self.hidden_size = hidden_size
        self.output_size = output_size
        self.embedding = nn.Embedding(self.output_size, self.hidden_size)

        if attn_model != None:
            self.attn = Attn(attn_model, hidden_size)
        self.RNN = nn.GRU(self.hidden_size, self.hidden_size, num_layers=2)
        self.out = nn.Linear(self.hidden_size, self.output_size)

    def forward(self, word_input, last_context, last_hidden, encoder_outputs):
        # Get the embedding of the current input word (last output word)
        word_embedded = self.embedding(word_input).view(1, 1, -1)  # S=1 x B x N

        # Combine embedded input word and last context, run through RNN
        rnn_input = torch.cat((word_embedded, last_context.unsqueeze(0)), 2)
        rnn_output, hidden = self.RNN(rnn_input, last_hidden)

        # Calculate attention from current RNN state and all encoder outputs; apply to encoder outputs
        attn_weights = self.attn(rnn_output.squeeze(0), encoder_outputs)
        context = attn_weights.bmm(encoder_outputs.transpose(0, 1))  # B x 1 x N

        # Final output layer (next word prediction) using the RNN hidden state and context vector
        rnn_output = rnn_output.squeeze(0)  # S=1 x B x N -> B x N
        context = context.squeeze(1)       # B x S=1 x N -> B x N
        output = F.log_softmax(self.out(torch.cat((rnn_output, context), 1)))

        # Return final output, hidden state, and attention weights (for visualization)
        return output, context, hidden, attn_weights

    def init_hidden(self, batch_size):
        hidden = Variable(torch.zeros(1, batch_size, self.hidden_size))
        if USE_CUDA:
            return hidden.cuda()
        else:
            return hidden
