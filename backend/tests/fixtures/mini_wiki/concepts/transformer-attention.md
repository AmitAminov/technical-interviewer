# Transformer Attention

**Summary**: The transformer architecture replaces recurrence with self-attention, letting every token attend to every other token in a sequence so the model can capture long-range dependencies in parallel.

The transformer processes an input sequence of token embeddings through
stacked layers of multi-head self-attention and position-wise feed-forward
networks. Self-attention computes query, key, and value projections of each
token; attention weights are the softmax of scaled dot products between
queries and keys, and each token's output is the attention-weighted sum of the
values. Because dot products grow with dimension, the scores are divided by
the square root of the head dimension before the softmax, which stabilizes
gradients.

## Multi-head attention and complexity

Multiple attention heads let the model attend to different relational patterns
simultaneously: one head may track syntactic agreement while another follows
coreference. The price of full self-attention is quadratic time and memory in
the sequence length, which motivates efficient variants such as sliding-window
attention, linear attention approximations, and key-value caching during
autoregressive decoding. Positional information is injected with sinusoidal
encodings, learned positions, or rotary position embeddings, since attention
itself is permutation invariant. See [[embeddings]] for how tokens become
vectors in the first place.

## Why transformers won

Compared with recurrent networks, transformers train in parallel across the
whole sequence, scale gracefully to billions of parameters, and transfer well
after pretraining on large corpora. Large language models are essentially
deep decoder-only transformers trained with next-token prediction, then
adapted with fine-tuning or retrieval-augmented generation for downstream
tasks.

## Related pages

- [[embeddings]]
- [[large-language-models]]
- [[fine-tuning]]
