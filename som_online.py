import numpy as np
import time
import logging
import cProfile

from progressbar import progressbar


logger = logging.getLogger(__name__)


class Som(object):

    def __init__(self, width, height, dim, learning_rate):

        self.scaling_factor = max(width, height) / 2
        self.scaler = 0
        self.learning_rate = learning_rate

        self.width = width
        self.height = height
        self.weights = np.random.normal(0, 0.1, size=(width * height, dim))
        self.grid = None
        self.grid_distances = None

        self._index_dict = {idx: (idx // self.height, idx % self.height) for idx in range(self.weights.shape[0])}
        self._coord_dict = {v: k for k, v in self._index_dict.items()}

        self.trained = False

    def train(self, data, samples=100000):
        """
        Fits the SOM to some data for a number of epochs.
        As the learning rate is decreased proportionally to the number
        of epochs, incrementally training a SOM is not feasible.

        :param data: The data on which to train
        :return: None
        """

        # Scaler ensures that the neighborhood radius is 0 at the end of training
        # given a square map.
        self.scaler = samples / np.log(self.scaling_factor)

        # Local copy of learning rate.
        learning_rate = self.learning_rate

        # First history

        sample_range = np.arange(len(data))

        for sample in progressbar(range(samples)):

            x = data[np.random.choice(sample_range)]

            # Calculate the radius to see which BMUs attract one another
            map_radius = self.scaling_factor * np.exp(-sample / self.scaler)

            # Create the helper grid, which absolves the need for expensive
            # euclidean products
            self.grid, self.grid_distances = self._distance_grid(map_radius)

            # Get the indices of the Best Matching Units given the data.
            # bmus = self._get_bmus(data, self.weights)

            # weights_summed_squared = np.sum(np.power(self.weights, 2), axis=1)

            bmus = self._get_bmu(x, self.weights)

            # Convert the indices of the BMUs to coordinates (x, y)
            coords = self._index_dict[bmus]

            # Look up which neighbors are close enough to influence
            indices, scores = self._find_neighbors(coords[0], coords[1])
            # Calculate the influence
            influence = self._calculate_influence(scores, map_radius)

            # Update all units which are in range
            self._update(x, self.weights, indices, influence, learning_rate)

            # Update learning rate
            learning_rate = self.learning_rate * np.exp(-sample/samples)

        self.trained = True

    def predict(self, x):
        """
        Predicts node identity for input data.
        Similar to a clustering procedure.

        :param x: The input data.
        :return: A list of indices
        """

        # Return the indices of the BMU which matches the input data most
        weights_summed_squared = np.sum(np.power(self.weights, 2), axis=1)
        return np.array(self._get_bmu(x, self.weights, weights_summed_squared))

    def predict_pseudo_proba(self, x):

        if not self.trained:
            raise ValueError("Not trained yet")

        weights_summed_squared = np.sum(np.power(self.weights, 2), axis=1)
        return dict(enumerate(self._euclid(x, self.weights, weights_summed_squared)))

    def map_weights(self):
        """
        Retrieves the grid as a list of lists of weights. For easy visualization.

        :return: A three-dimensional Numpy array of values (width, height, data_dim)
        """

        mapped_weights = []

        for x in range(self.width):
            x *= self.height
            temp = []
            for y in range(self.height):
                temp.append(self.weights[x + y])

            mapped_weights.append(temp)

        return np.array(mapped_weights)

    def _indices_to_coords(self, indices):
        """
        Helper function: converts a list of indices to a list of (x, y) coordinates,
        based on the width and height of the map.

        :param indices: A list of ints, representing the indices.
        :return: A list of tuples, (x, y).
        """

        return [self._index_dict[idx] for idx in indices]

    def _coords_to_indices(self, coords):
        """
        Helper function, converts a list of coordinates (x, y) to a list of indices.

        :param coords: A list of tuples, (x, y)
        :return: A list of indices.
        """

        return [self._coord_dict[tup] for tup in coords]

    def _find_neighbors(self, center_x, center_y):
        """
        Finds the nearest neighbors, based on the current grid.
        see _create_grid.

        Simply put, the radius of the nearest neighbor search only changes once per epoch,
        and hence there is no need to calculate it for every node.
        So, we create a radius_grid, which we move around, depending on the
        coordinates of the current node.

        :param center_x: An integer, representing the x coordinate
        :param center_y: An integer, representing the y coordinate
        :return: a tuple of indices and distances to the nodes at these indices.
        """

        # Add the current coordinates to the grid.
        temp_x = self.grid[0] + center_x
        temp_y = self.grid[1] + center_y

        x_cond = [np.logical_and(temp_x >= 0, temp_x < self.width)]
        y_cond = [np.logical_and(temp_y >= 0, temp_y < self.height)]

        mask = np.logical_and(x_cond, y_cond).ravel()

        temp_x = temp_x[mask]
        temp_y = temp_y[mask]
        distances = self.grid_distances[mask]

        return self._coords_to_indices(zip(temp_x, temp_y)), distances

    def _distance_grid(self, radius):
        """
        Creates a grid for easy processing of nearest neighbor searches.

        As explained above, the radius only changes once per epoch, and distances
        between nodes do not differ. Hence, there is no reason to calculate
        distances each time we want to know nearest neighbors to some node.

        Could be faster with aggressive caching.

        :param radius: The current radius.
        :return: The grid itself, and the distances for each grid.
        These are represented as a list of coordinates of things which are within distance,
        and a list with the same dimensionality, representing the distances.
        """

        # Radius never needs to be higher than the actual dimensionality
        radius = min(max(self.width, self.height), radius)

        # Cast to int for indexing
        radint = int(radius)

        # Define the vector which is added to the grid
        # We use squared euclidean distance, so we raise to the power of 2
        adder = np.power([abs(x) for x in range(-radint, radint+1)], 2)

        # Adder looks like this for radius 2
        # [4 1 0 1 4]

        # Double the radius + 1 is the size of the grid
        double = (int(radius) * 2) + 1

        grid = np.zeros((double, double))

        for index in range(double):
            grid[index, :] += adder
            grid[:, index] += adder

        # Grid now looks like (for radius 2):
        #
        # [[ 8.  5.  4.  5.  8.]
        #  [ 5.  2.  1.  2.  5.]
        #  [ 4.  1.  0.  1.  4.]
        #  [ 5.  2.  1.  2.  5.]
        #  [ 8.  5.  4.  5.  8.]]

        # We are doing euclidean distance, so sqrt
        grid = np.sqrt(grid)

        # Grid now looks like this:
        # [[ 2.82842712  2.23606798  2.          2.23606798  2.82842712]
        #  [ 2.23606798  1.41421356  1.          1.41421356  2.23606798]
        #  [ 2.          1.          0.          1.          2.        ]
        #  [ 2.23606798  1.41421356  1.          1.41421356  2.23606798]
        #  [ 2.82842712  2.23606798  2.          2.23606798  2.82842712]]

        where = np.where(grid < radius)

        return np.array(where) - radint, grid[where]

    @staticmethod
    def _calculate_influence(distances, map_radius):
        """
        Calculates influence, which can be described as a node-specific
        learning rate, conditioned on distance

        :param distances: A vector of distances
        :param map_radius: The current radius
        :return: A vector of scores
        """

        return np.exp(-(distances ** 2 / map_radius ** 2))

    def _update(self, input_vector, weights, indices, influence, learning_rate):
        """
        Updates the nodes, conditioned on the input vector,
        the influence, as calculated above, and the learning rate.

        :return: None
        """

        if not len(indices):
            return

        influence = np.repeat(influence, input_vector.shape[0]).reshape(influence.shape[0], input_vector.shape[0])
        weights[indices] += influence * (learning_rate * (input_vector - weights[indices]))

        return weights

    def _get_bmu(self, x, weights):
        """
        Gets the best matching units, based on euclidean distance.

        :param x: The input vector
        :param weights: The weight vectors
        :return: A list of integers, representing the indices of the best matching units.
        """

        return np.argmin(self._euclid(x, weights))

    @staticmethod
    def _euclid(x, weights):

        return [np.linalg.norm(w) for w in weights - x]

if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO)

    colors = np.array(
         [[0., 0., 0.],
          [0., 0., 1.],
          [0., 0., 0.5],
          [0.125, 0.529, 1.0],
          [0.33, 0.4, 0.67],
          [0.6, 0.5, 1.0],
          [0., 1., 0.],
          [1., 0., 0.],
          [0., 1., 1.],
          [1., 0., 1.],
          [1., 1., 0.],
          [1., 1., 1.],
          [.33, .33, .33],
          [.5, .5, .5],
          [.66, .66, .66]])

    colors = np.array(colors)

    '''colors = []

    for x in range(10):
        for y in range(10):
            for z in range(10):
                colors.append((x/10, y/10, z/10))

    colors = np.array(colors)'''

    '''addendum = np.arange(len(colors) * 10).reshape(len(colors) * 10, 1) / 10

    colors = np.array(colors)
    colors = np.repeat(colors, 10).reshape(colors.shape[0] * 10, colors.shape[1])

    print(colors.shape, addendum.shape)

    colors = np.hstack((colors,addendum))
    print(colors.shape)'''

    color_names = \
        ['black', 'blue', 'darkblue', 'skyblue',
         'greyblue', 'lilac', 'green', 'red',
         'cyan', 'violet', 'yellow', 'white',
         'darkgrey', 'mediumgrey', 'lightgrey']

    s = Som(50, 50, 3, 0.1)
    start = time.time()
    history = s.train(samples=10000, data=colors)

    # bmu_history = np.array(bmu_history).T
    print("Took {0} seconds".format(time.time() - start))

    '''from visualization.umatrix import UMatrixView

    for idx, x_w in enumerate(history):

        x, weight = x_w

        view = UMatrixView(500, 500, 'dom')
        view.create(weight, DataCL2, s.width, s.height, x)
        view.save("junk_viz/_{0}.svg".format(idx))

        print("Made {0}".format(idx))'''