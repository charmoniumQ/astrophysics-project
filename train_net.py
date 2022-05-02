from tensorflow import keras
from keras_unet.models import vanilla_unet


def main(voxels_per_side: int, padding: int):
    latent_dim = 64
    learning_rate = 0.0003

    box_size = padding * 2 + voxels_per_side

    # Create the discriminator.
    discriminator = keras.Sequential(
        [
            keras.layers.InputLayer((28, 28, discriminator_in_channels)),
            keras.layers.Conv2D(64, (3, 3), strides=(2, 2), padding="same"),
            keras.layers.LeakyReLU(alpha=0.2),
            keras.layers.Conv2D(128, (3, 3), strides=(2, 2), padding="same"),
            keras.layers.LeakyReLU(alpha=0.2),
            keras.layers.GlobalMaxPooling2D(),
            keras.layers.Dense(1),
        ],
        name="discriminator",
    )

    # Create the generator.
    generator = vanilla_unet(input_shape=(box_size,) * 3, num_classes=latent_dim)
    class ConditionalGAN(keras.Model):
        def __init__(self, discriminator, generator, latent_dim):
            super(ConditionalGAN, self).__init__()
            self.discriminator = discriminator
            self.generator = generator
            self.latent_dim = latent_dim
            self.gen_loss_tracker = keras.metrics.Mean(name="generator_loss")
            self.disc_loss_tracker = keras.metrics.Mean(name="discriminator_loss")

        @property
        def metrics(self):
            return [self.gen_loss_tracker, self.disc_loss_tracker]

        def compile(self, d_optimizer, g_optimizer, loss_fn):
            super(ConditionalGAN, self).compile()
            self.d_optimizer = d_optimizer
            self.g_optimizer = g_optimizer
            self.loss_fn = loss_fn

        def train_step(self, data):
            # Unpack the data.
            real_images, one_hot_labels = data

            # Add dummy dimensions to the labels so that they can be concatenated with
            # the images. This is for the discriminator.
            image_one_hot_labels = one_hot_labels[:, :, None, None]
            image_one_hot_labels = tf.repeat(
                image_one_hot_labels, repeats=[image_size * image_size]
            )
            image_one_hot_labels = tf.reshape(
                image_one_hot_labels, (-1, image_size, image_size, num_classes)
            )

            # Sample random points in the latent space and concatenate the labels.
            # This is for the generator.
            batch_size = tf.shape(real_images)[0]
            random_latent_vectors = tf.random.normal(shape=(batch_size, self.latent_dim))
            random_vector_labels = tf.concat(
                [random_latent_vectors, one_hot_labels], axis=1
            )

            # Decode the noise (guided by labels) to fake images.
            generated_images = self.generator(random_vector_labels)

            # Combine them with real images. Note that we are concatenating the labels
            # with these images here.
            fake_image_and_labels = tf.concat([generated_images, image_one_hot_labels], -1)
            real_image_and_labels = tf.concat([real_images, image_one_hot_labels], -1)
            combined_images = tf.concat(
                [fake_image_and_labels, real_image_and_labels], axis=0
            )

            # Assemble labels discriminating real from fake images.
            labels = tf.concat(
                [tf.ones((batch_size, 1)), tf.zeros((batch_size, 1))], axis=0
            )

            # Train the discriminator.
            with tf.GradientTape() as tape:
                predictions = self.discriminator(combined_images)
                d_loss = self.loss_fn(labels, predictions)
            grads = tape.gradient(d_loss, self.discriminator.trainable_weights)
            self.d_optimizer.apply_gradients(
                zip(grads, self.discriminator.trainable_weights)
            )

            # Sample random points in the latent space.
            random_latent_vectors = tf.random.normal(shape=(batch_size, self.latent_dim))
            random_vector_labels = tf.concat(
                [random_latent_vectors, one_hot_labels], axis=1
            )

            # Assemble labels that say "all real images".
            misleading_labels = tf.zeros((batch_size, 1))

            # Train the generator (note that we should *not* update the weights
            # of the discriminator)!
            with tf.GradientTape() as tape:
                fake_images = self.generator(random_vector_labels)
                fake_image_and_labels = tf.concat([fake_images, image_one_hot_labels], -1)
                predictions = self.discriminator(fake_image_and_labels)
                g_loss = self.loss_fn(misleading_labels, predictions)
            grads = tape.gradient(g_loss, self.generator.trainable_weights)
            self.g_optimizer.apply_gradients(zip(grads, self.generator.trainable_weights))

            # Monitor loss.
            self.gen_loss_tracker.update_state(g_loss)
            self.disc_loss_tracker.update_state(d_loss)
            return {
                "g_loss": self.gen_loss_tracker.result(),
                "d_loss": self.disc_loss_tracker.result(),
            }

    cond_gan = ConditionalGAN(descriminator, generator, )
    cond_gan.compile(
        d_optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        g_optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        loss_fn=keras.losses.BinaryCrossentropy(from_logits=True),
    )

    cond_gan.fit(dataset, epochs=20)


