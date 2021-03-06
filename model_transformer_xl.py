""" pytorch TransformerXL """
import torch
import torch.nn as nn
from util_transformer import TransformerDecoder

__all__ = ["TransformerXL"]


EPS = 1e-5  # for numeric stability
CLAMP_EXP = 15  # to avoid exploding exponentiation


class TransformerXL(nn.Module):
    """ Transformer XL """

    def __init__(self,
                 n_layer: int,
                 n_embedding: int,
                 n_state_ffn: int,
                 n_head: int,
                 n_context: int,
                 dropout_residual: float,
                 dropout_attention: float,
                 dropout_embedding: float,
                 vocab_size: int,
                 n_positional_embedding: int,
                 initializer_range: float = 0.02):
        """ Transformer XL

         Parameter
        -----------------
        n_layer: int
            number of layer
        n_embedding: int
            embedding dimension
        n_state_ffn: int
            intermediate state dimension
        n_head: int
            number of attention head
        dropout_residual: float
        dropout_attention: float
        dropout_embedding: float
        n_context: int
            context length
        vocab_size: int
        initializer_range: float
        """
        super().__init__()

        # word embedding/decoding and position embedding
        self.word_embedding = nn.Embedding(vocab_size, n_embedding)
        # nn.Embedding(a, b).weight.shape -> (a, b), while nn.Linear(a, b) -> (b, a)
        self.word_decoding = nn.Linear(n_embedding, vocab_size, bias=False)
        self.word_decoding.weight = self.word_embedding.weight
        self.dropout_embedding = nn.Dropout(dropout_embedding)
        self.transformer_decoder = TransformerDecoder(
            n_layer=n_layer,
            n_embedding=n_embedding,
            n_state_ffn=n_state_ffn,
            n_head=n_head,
            dropout_residual=dropout_residual,
            dropout_attention=dropout_attention,
            dropout_embedding=dropout_embedding,
            n_context=n_context,
            n_positional_embedding=n_positional_embedding
        )
        self.__initializer_range = initializer_range
        self.init_weight()

    def __init_weight(self, _module):
        if isinstance(_module, (nn.Linear, nn.Embedding)):
            _module.weight.data.normal_(mean=0.0, std=self.__initializer_range)
            if isinstance(_module, nn.Linear) and _module.bias is not None:
                _module.bias.data.zero_()
        elif isinstance(_module, nn.LayerNorm):
            _module.bias.data.zero_()
            _module.weight.data.fill_(1.0)

    def init_weight(self):
        self.apply(self.__init_weight)

    def forward(self, x, cached_key_value: list = None, max_cache_length: int=None):
        """ model output

         Parameter
        -------------
        x: token id batch tensor (batch, sequence_length)
        cached_key_value: cached key/value tensor

         Return
        -------------
        (output, prob, pred):
            output: raw output from Transformer decoder (sequence_length, batch, vocab size)
            prob: softmax activated output (sequence_length, batch, vocab size)
            pred: prediction (sequence_length, batch)
        cached_key_value: new cached_key_value
        """

        # get embedding
        w_embedding = self.word_embedding(x)  # dropout embeddings
        # transform
        logit, cached_key_value = self.transformer_decoder(w_embedding, cached_key_value, max_cache_length)
        cached_key_value = self.repackage_hidden(cached_key_value)

        # get output
        batch, seq, dim = logit.size()
        logit = logit.view(batch * seq, dim)  # (batch, seq, dim) -> (batch * seq, dim)
        output = self.word_decoding(logit).float()  # (batch * seq, dim) -> (batch * seq, vocab)
        output = output.clamp(min=-CLAMP_EXP, max=CLAMP_EXP)

        # get pred/prob
        pred = torch.max(output, dim=1)[1].view(batch, seq)
        prob = torch.nn.functional.softmax(output, dim=1).view(batch, seq, output.size(1))
        output = output.view(batch, seq, output.size(1))
        return (output, prob, pred), cached_key_value

    def repackage_hidden(self, h):
        """Wraps hidden states in new Tensors, to detach them from their history."""

        if isinstance(h, torch.Tensor):
            return h.detach()
        else:
            return tuple(self.repackage_hidden(v) for v in h)


if __name__ == '__main__':
    # debug
    torch.manual_seed(1111)
    _batch, _seq, _dim = 10, 12, 100
    sample = torch.ones((_batch, _seq), dtype=torch.long)
    sample_output = torch.ones((_batch, _seq), dtype=torch.long) * 2
    print('sample input:', sample.size())

    gpt = TransformerXL(
        n_layer=2,
        n_embedding=_dim,
        n_state_ffn=200,
        n_head=int(_dim / 25),
        n_context=_seq,
        dropout_residual=.1,
        dropout_attention=.1,
        dropout_embedding=.1,
        vocab_size=1000,
        n_positional_embedding=10,
        initializer_range=0.001
    )
    print('\n * 1')
    (_output, _prob, _pred), kv = gpt(sample)
    print('outputs:', _output.shape, _prob.shape, _pred.shape)
    print(len(kv), len(kv[0]), kv[0][0].shape)

    print('\n * 2')
    (_output, _prob, _pred), kv = gpt(sample)
    print('outputs:', _output.shape, _prob.shape, _pred.shape)
    print(len(kv), len(kv[0]), kv[0][0].shape)

    print('\n * 3')
    (_output, _prob, _pred), kv = gpt(sample, kv)
    print('outputs:', _output.shape, _prob.shape, _pred.shape)
    print(len(kv), len(kv[0]), kv[0][0].shape)

    print('\n * 4')
    (_output, _prob, _pred), kv = gpt(sample, kv)
    _logit = _output.view(-1, _output.size(-1))
    loss = nn.CrossEntropyLoss()(_logit, sample_output.view(-1))
    loss.backward()
    print(loss)

    (_output, _prob, _pred), kv = gpt(sample, kv)
    _logit = _output.view(-1, _output.size(-1))
    loss = nn.CrossEntropyLoss()(_logit, sample_output.view(-1))
    loss.backward()
    print(loss)

