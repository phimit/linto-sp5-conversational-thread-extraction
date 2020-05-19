import logging
from typing import Dict, List, Iterable
import torch

#from allennlp.data.dataset_readers import SnliReader
from allennlp.data.dataset_readers.dataset_reader import DatasetReader
# to be checked: reads a text as a list of sentences
from allennlp.data.dataset_readers import TextClassificationJsonReader
from allennlp.data.fields import Field
from allennlp.data.fields import LabelField
from allennlp.data.fields import TextField, ListField
from allennlp.data.instance import Instance
from allennlp.data.token_indexers import TokenIndexer
from allennlp.data.tokenizers import Tokenizer
from allennlp.modules.seq2vec_encoders import BertPooler
# should be a better way
from allennlp.modules.stacked_bidirectional_lstm import StackedBidirectionalLstm
from allennlp.models.model import Model
from allennlp.training.metrics import CategoricalAccuracy
from allennlp.nn.util import get_text_field_mask



from overrides import overrides

logger = logging.getLogger(__name__)


@DatasetReader.register("chat_reader")
class ChatReader(DatasetReader):
    """
    Reads a file for chat problems
    
    just for testing encoding, not necessarily the right data format reader       
     
    Parameters
    ----------
    tokenizer : ``Tokenizer``, optional (default=``SpacyTokenizer()``)
    token_indexers : ``Dict[str, TokenIndexer]``, optional (default=``{"tokens": SingleIdTokenIndexer()}``)
        We similarly use this for both the premise and the hypothesis.  See :class:`TokenIndexer`.

    TODO: 
    """
    def __init__(
        self,
        tokenizer: Tokenizer = None,
        token_indexers: Dict[str, TokenIndexer] = None,
        max_sequence_length: int = None,
        lazy: bool = False,
    ) -> None:
        super(ChatReader, self).__init__(lazy)
        self._tokenizer = tokenizer 
        self._max_sequence_length = max_sequence_length
        self._token_indexers = token_indexers

    @overrides
    def _read(self, file_path: str) -> Iterable[Instance]:
        # if `file_path` is a URL, redirect to the cache
        #file_path = cached_path(file_path)

        with open(file_path, "r") as data_file:
            logger.info("Reading instances from lines in file at: %s", file_path)
            #header = next(data_file)
            inst_tokens = []
            inst_deps = []
            idx = 0
            for line in data_file:
                if line.strip()=="":
                    yield self.text_to_instance(inst_tokens,inst_deps)
                    idx = 0
                    inst_tokens, inst_deps = [],[]
                else:
                    head, turn = line.strip().split('\t')
                    inst_tokens.append(self._tokenizer.tokenize(turn))
                    inst_deps.append((idx,head))
                    idx = idx 
            yield self.text_to_instance(inst_tokens,inst_deps)

    @overrides
    def text_to_instance(
        self,  # type: ignore
        inst_tokens: Iterable,
        inst_deps: Iterable,
    ) -> Instance:
        # roughly similar to what happens in TextClassifierJson datareader
        lines_field = ListField([TextField(tokenized_line,self._token_indexers) for tokenized_line in inst_tokens])
        # labels are head index for each turn; root is "root"
        target = ListField([LabelField(label=head) for idx,head in inst_deps])  # or simply LabelField
        instance = Instance({'lines': lines_field, 'labels': target})
        # mock label for testing of model as classification of a chat ; force label = 0
        instance = Instance({'lines': lines_field, 'labels': 0})
        return instance


# tokenized_lines: List[List[Token]]
# lines_field = ListField([TextField(tokenized_line) for tokenized_line in tokenized_lines])
# target = ListField([LabelField(label=label) for label in labels)  # or simply LabelField
# instance = Instance({'lines': lines_field, 'labels': target})

#The things you need to be careful about are when you call your TextFieldEmbedder you need to add num_wrapping_dims=1, and you need to wrap your Seq2Vec encoder with TimeDistributed(). These are both in your Model.forward() method. Let me know if you need more detail.

#Adding num_embedding_dims =1 works, it turns out I didn't need to TimeDistributed the encoder. 

# TODO: turn encoder, following this kind of embedding for turns 
"""
"text_field_embedder": {
        "tokens": {
        "type": "sequence_encoding",
        "embedding": {
            "embedding_dim": 100
        },
        "encoder": {
            "type": "gru",
            "input_size": 100,
            "hidden_size": 50,
            "num_layers": 2,
            "dropout": 0.25,
            "bidirectional": true
        }
                }
"""
# then use the rest of graph_parser config changing the text_field_embedder, and removing pos tags and label prediction, sth like: 
# must check how dependencies are encoded in that -> "dataset_reader":{"type":"semantic_dependencies"}
"""
"model": {
      "type": "graph_parser",
      "text_field_embedder": {
        "token_embedders": {
          "tokens": {
            "type": "embedding",
            "embedding_dim": 100,
            "pretrained_file": "/home/markn/data/glove/glove.6B/glove.6B.100d.txt",
            "trainable": true,
            "sparse": true
          }
        }
      },
      "pos_tag_embedding":{
        "embedding_dim": 100,
        "vocab_namespace": "pos",
        "sparse": true
      },
      "encoder": {
        "type": "stacked_bidirectional_lstm",
        "input_size": 200,
        "hidden_size": 400,
        "num_layers": 3,
        "recurrent_dropout_probability": 0.3,
        "use_highway": true
      },
      "arc_representation_dim": 500,
      "tag_representation_dim": 100,
      "dropout": 0.3,
      "input_dropout": 0.3,
      "initializer": [
        [".*feedforward.*weight", {"type": "xavier_uniform"}],
        [".*feedforward.*bias", {"type": "zero"}],
        [".*tag_bilinear.*weight", {"type": "xavier_uniform"}],
        [".*tag_bilinear.*bias", {"type": "zero"}],
        [".*weight_ih.*", {"type": "xavier_uniform"}],
        [".*weight_hh.*", {"type": "orthogonal"}],
        [".*bias_ih.*", {"type": "zero"}],
        [".*bias_hh.*", {"type": "lstm_hidden_bias"}]]
    },
"""


class ChatClassification(Model):


    def __init__(self,vocab, pretrained_model: str="bert-base-uncased", requires_grad: bool = True):
        super(ChatClassification, self).__init__(vocab)
        self.turn_pooler = BertPooler(pretrained_model,requires_grad,dropout=0.0)
        self.chat_encoder = StackedBidirectionalLstm(hidden_size= 400,
                                                     input_size= 768,
                                                     num_layers= 1,
                                                     recurrent_dropout_probability=0.3,
                                                     use_highway=True)
        self.classif_layer = torch.nn.Linear(in_features=self.chat_encoder.get_output_dim(),
                                             out_features=2)
        self.accuracy = CategoricalAccuracy()

        
    def forward(self,
                all_turns, 
                label = None
            ):
        turns_embeddings = [self.turn_pooler(turn) for turn in all_turns]
        output_seq, final_h, final_c = self.chat_encoder(turns_embeddings)
        logits = self.classif_layer(final_h)
        output = {"tag_logits": logits}

        if label is not None:
            self.accuracy(logits, label)
            output["loss"] = 0#torch.nn.CrossEntropyLoss(logits, label.squeeze(-1))

        return output


    def get_metrics(self, reset: bool = False) -> Dict[str, float]:
        return {"accuracy": self.accuracy.get_metric(reset)}
        

if __name__=="__main__":
    
    from allennlp.data.tokenizers import Token, Tokenizer, WordTokenizer, PretrainedTransformerTokenizer
    from allennlp.data.token_indexers import PretrainedTransformerIndexer
    from allennlp.data.vocabulary import Vocabulary
    #from allennlp.training.trainer import Trainer


    # for pretrained model
    tokenizer = PretrainedTransformerTokenizer(
        model_name="bert-base-uncased",
        do_lowercase=True,
        )
    

    token_indexers = PretrainedTransformerIndexer(
        model_name="bert-base-uncased",
        do_lowercase=True
        )
    reader = ChatReader(
        tokenizer=tokenizer,
        token_indexers=token_indexers,
        #use_pretrained_model=True
        )
    train_instances = reader.read("./train_dummy.tsv")
    vocab = Vocabulary.from_instances(train_instances)
    model = ChatClassification(vocab)
    trainer = Trainer(model=model)
    trainer.train()