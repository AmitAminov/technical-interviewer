# Gradient Descent

**Summary**: Gradient descent is an iterative optimization algorithm that minimizes a loss function by repeatedly stepping in the direction of the negative gradient of the loss with respect to the model parameters.

Gradient descent is the workhorse of modern machine learning training. At each
iteration the algorithm computes the gradient of the loss function with respect
to every parameter, then updates the parameters by subtracting the gradient
scaled by a learning rate. A learning rate that is too large makes the loss
diverge or oscillate, while a learning rate that is too small makes convergence
painfully slow. The loss landscape of deep networks is non-convex, yet in
practice gradient descent with sensible initialization finds parameter settings
that generalize well.

## Variants

Batch gradient descent computes the exact gradient over the entire training
set, which is accurate but expensive for large datasets. Stochastic gradient
descent (SGD) estimates the gradient from a single example, trading noise for
speed, and mini-batch gradient descent strikes the practical balance used
almost everywhere: gradients averaged over small batches of 32 to 1024
examples. Momentum accumulates an exponentially decaying average of past
gradients to damp oscillations, and adaptive methods such as Adam scale each
parameter's step size by an estimate of the gradient's second moment. See also
[[backpropagation]], which is the algorithm that computes these gradients
efficiently in neural networks.

## Convergence and learning rate schedules

For convex objectives with a suitable step size, gradient descent provably
converges to the global minimum; for deep learning the theory is weaker but
the practice is mature. Common learning rate schedules include step decay,
cosine annealing, and linear warmup followed by decay. Warmup avoids unstable
early updates when the parameters are far from any good region. Gradient
clipping caps the norm of the update and prevents exploding gradients in
recurrent or very deep models.

## Related pages

- [[backpropagation]]
- [[loss-functions]]
- [[adam-optimizer]]
