"""
Disjoint set data structure.
Stolen shamelessly from https://github.com/scipy/scipy/blob/main/scipy/_lib/_disjoint_set.py
 because it does excess unnecessary 'in dict' checks instead of on-the-fly adding elements as 1-sets.
 This version is updated to just dynamically add a new set for any missing item. So an empty FastDisjointSet
 can have .merge(2, 3) called on it and will make a set for 2, and a set for 3, and then merge them.
 Should pretty much NEVER need to call .add externally...

Pure python, fork this for custom tile set building structures that need to build tile trees while maintaining calculated values (and just merge some mergeable obj instead of just _size).
TODO build tileislands out of this structure?
TODO swap off of dicts for stuff based on tileIndex, use TileSet instead, maybe?
"""
from __future__ import annotations

import typing

from Interfaces import MapMatrixInterface
from base.client.tile import Tile


class FastDisjointSet:
    """ Disjoint set data structure for incremental connectivity queries.

    Attributes
    ----------
    n_subsets : int
        The number of subsets.

    Methods
    -------
    add
    merge
    connected
    subset
    subset_size
    subsets
    __getitem__

    Notes
    -----
    This class implements the disjoint set [1]_, also known as the *union-find*
    or *merge-find* data structure. The *find* operation (implemented in
    `__getitem__`) implements the *path halving* variant. The *merge* method
    implements the *merge by size* variant.

    References
    ----------
    .. [1] https://en.wikipedia.org/wiki/Disjoint-set_data_structure

    Examples
    --------

    Initialize a disjoint set:

    >>> disjoint_set = FastDisjointSet([1, 2, 3, 'a', 'b'])

    Merge some subsets:

    >>> disjoint_set.merge(1, 2)
    True
    >>> disjoint_set.merge(3, 'a')
    True
    >>> disjoint_set.merge('a', 'b')
    True
    >>> disjoint_set.merge('b', 'b')
    False

    Find root elements:

    >>> disjoint_set[2]
    1
    >>> disjoint_set['b']
    3

    Test connectivity:

    >>> disjoint_set.connected(1, 2)
    True
    >>> disjoint_set.connected(1, 'b')
    False

    List elements in disjoint set:

    >>> list(disjoint_set)
    [1, 2, 3, 'a', 'b']

    Get the subset containing 'a':

    >>> disjoint_set.subset('a')
    {'a', 3, 'b'}

    Get the size of the subset containing 'a' (without actually instantiating
    the subset):

    >>> disjoint_set.subset_size('a')
    3

    Get all subsets in the disjoint set:

    >>> disjoint_set.subsets()
    [{1, 2}, {'a', 3, 'b'}]
    """

    __slots__ = (
        'n_subsets',
        '_sizes',
        '_parents',
        '_nbrs',
        '_indices',
    )

    def __init__(self, elements=None):
        self.n_subsets = 0
        self._sizes = {}
        self._parents = {}
        # _nbrs is a circular linked list which links connected elements.
        self._nbrs = {}
        # _indices tracks the element insertion order in `__iter__`.
        self._indices = {}
        if elements is not None:
            for x in elements:
                self.add(x)

    def __iter__(self):
        """Returns an iterator of the elements in the disjoint set.

        Elements are ordered by insertion order.
        """
        return iter(self._indices)

    def __len__(self):
        return len(self._indices)

    def __contains__(self, x):
        return x in self._indices

    def add(self, x):
        """Add element `x` to disjoint set
        """
        if x in self._indices:
            return

        self._sizes[x] = 1
        self._parents[x] = x
        self._nbrs[x] = x
        self._indices[x] = len(self._indices)
        self.n_subsets += 1

    def __getitem__(self, x):
        """Find the root element of `x`.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        root : hashable object
            Root element of `x`.
        """
        indVal = self._indices.get(x, None)
        if indVal is None:
            self.add(x)
            indVal = self._indices[x]

        # find by "path halving"
        parents = self._parents
        while indVal != self._indices[parents[x]]:
            parents[x] = parents[parents[x]]
            x = parents[x]
            indVal = self._indices[x]
        return x

    def merge(self, x, y) -> bool:
        """Merge the subsets of `x` and `y`.

        The smaller subset (the child) is merged into the larger subset (the
        parent). If the subsets are of equal size, the root element which was
        first inserted into the disjoint set is selected as the parent.

        Parameters
        ----------
        x, y : hashable object
            Elements to merge.

        Returns
        -------
        merged : bool
            True if `x` and `y` were in disjoint sets, False otherwise.
        """
        xr = self[x]
        yr = self[y]
        if self._indices[xr] == self._indices[yr]:
            return False

        if (self._sizes[xr], self._indices[yr]) < (self._sizes[yr], self._indices[xr]):
            xr, yr = yr, xr
        self._parents[yr] = xr
        self._sizes[xr] += self._sizes[yr]
        self._nbrs[xr], self._nbrs[yr] = self._nbrs[yr], self._nbrs[xr]
        self.n_subsets -= 1
        return True

    def connected(self, x, y):
        """Test whether `x` and `y` are in the same subset.

        Parameters
        ----------
        x, y : hashable object
            Elements to test.

        Returns
        -------
        result : bool
            True if `x` and `y` are in the same set, False otherwise.
        """
        return self._indices[self[x]] == self._indices[self[y]]

    def subset(self, x):
        """Get the subset containing `x`.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        result : set
            Subset containing `x`.
        """

        result = [x]
        nxt = self._nbrs[x]
        while self._indices[nxt] != self._indices[x]:
            result.append(nxt)
            nxt = self._nbrs[nxt]
        return set(result)

        # result = {x}
        # nxt = self._nbrs[x]
        # while self._indices[nxt] != self._indices[x]:
        #     result.add(nxt)
        #     nxt = self._nbrs[nxt]
        # return result

    def subset_size(self, x):
        """Get the size of the subset containing `x`.

        Note that this method is faster than ``len(self.subset(x))`` because
        the size is directly read off an internal field, without the need to
        instantiate the full subset.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        result : int
            Size of the subset containing `x`.
        """
        return self._sizes[self[x]]

    def subsets(self):
        """Get all the subsets in the disjoint set.

        Returns
        -------
        result : list
            Subsets in the disjoint set.
        """
        result = []
        visited = set()
        for x in self:
            if x in visited:
                continue

            xset = self.subset(x)
            visited.update(xset)
            result.append(xset)

        return result

    def copy(self) -> FastDisjointSet:
        copy = FastDisjointSet()

        copy.n_subsets = self.n_subsets
        copy._sizes = self._sizes.copy()
        copy._parents = self._parents.copy()
        copy._nbrs = self._nbrs.copy()
        copy._indices = self._indices.copy()
        return copy


class FastDisjointTileSetSum(object):
    """ Disjoint set data structure for incremental connectivity queries. Sums things that can be added.

    Attributes
    ----------
    n_subsets : int
        The number of subsets.

    Methods
    -------
    add
    merge
    connected
    subset
    subset_size
    subsets
    __getitem__

    Notes
    -----
    This class implements the disjoint set [1]_, also known as the *union-find*
    or *merge-find* data structure. The *find* operation (implemented in
    `__getitem__`) implements the *path halving* variant. The *merge* method
    implements the *merge by size* variant.

    References
    ----------
    .. [1] https://en.wikipedia.org/wiki/Disjoint-set_data_structure

    Examples
    --------

    Initialize a disjoint set:

    >>> disjoint_set = FastDisjointSet([1, 2, 3, 'a', 'b'])

    Merge some subsets:

    >>> disjoint_set.merge(1, 2)
    True
    >>> disjoint_set.merge(3, 'a')
    True
    >>> disjoint_set.merge('a', 'b')
    True
    >>> disjoint_set.merge('b', 'b')
    False

    Find root elements:

    >>> disjoint_set[2]
    1
    >>> disjoint_set['b']
    3

    Test connectivity:

    >>> disjoint_set.connected(1, 2)
    True
    >>> disjoint_set.connected(1, 'b')
    False

    List elements in disjoint set:

    >>> list(disjoint_set)
    [1, 2, 3, 'a', 'b']

    Get the subset containing 'a':

    >>> disjoint_set.subset('a')
    {'a', 3, 'b'}

    Get the size of the subset containing 'a' (without actually instantiating
    the subset):

    >>> disjoint_set.subset_size('a')
    3

    Get all subsets in the disjoint set:

    >>> disjoint_set.subsets()
    [{1, 2}, {'a', 3, 'b'}]
    """
    __slots__ = (
        'n_subsets',
        '_sizes',
        '_sums',
        '_parents',
        '_value_lookup',
        '_nbrs',
        '_indices',
    )

    def __init__(self, valueLookup: MapMatrixInterface[float], elements: typing.Iterable[Tile] | None = None):
        self.n_subsets = 0
        self._sizes = {}
        self._sums = {}
        self._parents = {}
        self._value_lookup: MapMatrixInterface[float] = valueLookup
        # _nbrs is a circular linked list which links connected elements.
        self._nbrs = {}
        # _indices tracks the element insertion order in `__iter__`.
        self._indices = {}
        if elements is not None:
            for x in elements:
                self.add(x)

    def __iter__(self) -> typing.Iterable[Tile]:
        """Returns an iterator of the elements in the disjoint set.

        Elements are ordered by insertion order.
        """
        return iter(self._indices)

    def __len__(self):
        return len(self._indices)

    def __contains__(self, x: Tile):
        return x in self._indices

    def add(self, x: Tile):
        """Add element `x` to disjoint set
        """
        if x in self._indices:
            return

        self._sizes[x] = 1
        self._sums[x] = self._value_lookup.raw[x.tile_index]
        self._parents[x] = x
        self._nbrs[x] = x
        self._indices[x] = len(self._indices)
        self.n_subsets += 1

    def __getitem__(self, x: Tile):
        """Find the root element of `x`.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        root : hashable object
            Root element of `x`.
        """
        indVal = self._indices.get(x, None)
        if indVal is None:
            self.add(x)
            indVal = self._indices[x]

        # find by "path halving"
        parents = self._parents
        while indVal != self._indices[parents[x]]:
            parents[x] = parents[parents[x]]
            x = parents[x]
            indVal = self._indices[x]
        return x

    def merge(self, x: Tile, y: Tile) -> bool:
        """Merge the subsets of `x` and `y`.

        The smaller subset (the child) is merged into the larger subset (the
        parent). If the subsets are of equal size, the root element which was
        first inserted into the disjoint set is selected as the parent.

        Parameters
        ----------
        x, y : hashable object
            Elements to merge.

        Returns
        -------
        merged : bool
            True if `x` and `y` were in disjoint sets, False otherwise.
        """
        xr = self[x]
        yr = self[y]
        if self._indices[xr] == self._indices[yr]:
            return False

        if (self._sizes[xr], self._indices[yr]) < (self._sizes[yr], self._indices[xr]):
            xr, yr = yr, xr
        self._parents[yr] = xr
        self._sizes[xr] += self._sizes[yr]
        self._sums[xr] += self._sums[yr]
        self._nbrs[xr], self._nbrs[yr] = self._nbrs[yr], self._nbrs[xr]
        self.n_subsets -= 1
        return True

    def connected(self, x: Tile, y: Tile):
        """Test whether `x` and `y` are in the same subset.

        Parameters
        ----------
        x, y : hashable object
            Elements to test.

        Returns
        -------
        result : bool
            True if `x` and `y` are in the same set, False otherwise.
        """
        return self._indices[self[x]] == self._indices[self[y]]

    def subset_with_value(self, x: Tile) -> typing.Tuple[typing.Set[Tile], float]:
        """Get the subset containing `x`.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        result : set
            Subset containing `x`.
        """

        result = [x]
        nxt = self._nbrs[x]
        while self._indices[nxt] != self._indices[x]:
            result.append(nxt)
            nxt = self._nbrs[nxt]

        return set(result), self._sums[self[x]]

        # result = {x}
        # nxt = self._nbrs[x]
        # while self._indices[nxt] != self._indices[x]:
        #     result.add(nxt)
        #     nxt = self._nbrs[nxt]
        # return result

    def subset_size(self, x: Tile):
        """Get the size of the subset containing `x`.

        Note that this method is faster than ``len(self.subset(x))`` because
        the size is directly read off an internal field, without the need to
        instantiate the full subset.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        result : int
            Size of the subset containing `x`.
        """
        return self._sizes[self[x]]

    def subset_value(self, x: Tile):
        """Get the value of the subset containing `x`.

        Note that this method is faster than ``len(self.subset(x))`` because
        the value is directly read off an internal field, without the need to
        instantiate the full subset.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        result : int
            Size of the subset containing `x`.
        """
        return self._sums[self[x]]

    def subsets(self) -> typing.List[typing.Set[Tile]]:
        """Get all the subsets in the disjoint set.

        Returns
        -------
        result : list
            Subsets in the disjoint set.
        """
        result = []
        visited = set()
        for x in self:
            if x in visited:
                continue

            xset, val = self.subset_with_value(x)
            visited.update(xset)
            result.append(xset)

        return result

    def subsets_with_values(self) -> typing.List[typing.Tuple[typing.Set[Tile], float]]:
        """Get all the subsets in the disjoint set.

        Returns
        -------
        result : list of (subset, subset sum) in the disjoint set.
        """
        result = []
        visited = set()
        for x in self:
            if x in visited:
                continue

            xset, val = self.subset_with_value(x)
            visited.update(xset)
            result.append((xset, val))

        return result

    def copy(self) -> FastDisjointTileSetSum:
        copy = FastDisjointTileSetSum(self._value_lookup)

        copy.n_subsets = self.n_subsets
        copy._sizes = self._sizes.copy()
        copy._sums = self._sums.copy()
        copy._parents = self._parents.copy()
        copy._nbrs = self._nbrs.copy()
        copy._indices = self._indices.copy()
        return copy


class FastDisjointTileSetMultiSum(object):
    """ Disjoint set data structure for incremental connectivity queries. Sums things that can be added.

    Attributes
    ----------
    n_subsets : int
        The number of subsets.

    Methods
    -------
    add
    merge
    connected
    subset
    subset_size
    subsets
    __getitem__

    Notes
    -----
    This class implements the disjoint set [1]_, also known as the *union-find*
    or *merge-find* data structure. The *find* operation (implemented in
    `__getitem__`) implements the *path halving* variant. The *merge* method
    implements the *merge by size* variant.

    References
    ----------
    .. [1] https://en.wikipedia.org/wiki/Disjoint-set_data_structure

    Examples
    --------

    Initialize a disjoint set:

    >>> disjoint_set = FastDisjointSet([1, 2, 3, 'a', 'b'])

    Merge some subsets:

    >>> disjoint_set.merge(1, 2)
    True
    >>> disjoint_set.merge(3, 'a')
    True
    >>> disjoint_set.merge('a', 'b')
    True
    >>> disjoint_set.merge('b', 'b')
    False

    Find root elements:

    >>> disjoint_set[2]
    1
    >>> disjoint_set['b']
    3

    Test connectivity:

    >>> disjoint_set.connected(1, 2)
    True
    >>> disjoint_set.connected(1, 'b')
    False

    List elements in disjoint set:

    >>> list(disjoint_set)
    [1, 2, 3, 'a', 'b']

    Get the subset containing 'a':

    >>> disjoint_set.subset('a')
    {'a', 3, 'b'}

    Get the size of the subset containing 'a' (without actually instantiating
    the subset):

    >>> disjoint_set.subset_size('a')
    3

    Get all subsets in the disjoint set:

    >>> disjoint_set.subsets()
    [{1, 2}, {'a', 3, 'b'}]
    """
    __slots__ = (
        'n_subsets',
        '_sizes',
        '_sums',
        '_parents',
        '_value_lookups',
        '_nbrs',
        '_indices',
        '_num_vals',
    )

    def __init__(self, valueLookups: typing.List[MapMatrixInterface[float]], elements: typing.Iterable[Tile] | None = None):
        self.n_subsets = 0
        self._sizes = {}
        self._sums: typing.Dict[Tile, typing.List[float]] = {}
        self._parents = {}
        self._value_lookups: typing.List[MapMatrixInterface[float]] = valueLookups
        self._num_vals: int = len(valueLookups)
        # _nbrs is a circular linked list which links connected elements.
        self._nbrs = {}
        # _indices tracks the element insertion order in `__iter__`.
        self._indices = {}
        if elements is not None:
            for x in elements:
                self.add(x)

    def __iter__(self) -> typing.Iterable[Tile]:
        """Returns an iterator of the elements in the disjoint set.

        Elements are ordered by insertion order.
        """
        return iter(self._indices)

    def __len__(self):
        return len(self._indices)

    def __contains__(self, x: Tile):
        return x in self._indices

    def add(self, x: Tile):
        """Add element `x` to disjoint set
        """
        if x in self._indices:
            return

        self._sizes[x] = 1
        self._sums[x] = [v.raw[x.tile_index] for v in self._value_lookups]
        self._parents[x] = x
        self._nbrs[x] = x
        self._indices[x] = len(self._indices)
        self.n_subsets += 1

    def __getitem__(self, x: Tile):
        """Find the root element of `x`.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        root : hashable object
            Root element of `x`.
        """
        indVal = self._indices.get(x, None)
        if indVal is None:
            self.add(x)
            indVal = self._indices[x]

        # find by "path halving"
        parents = self._parents
        while indVal != self._indices[parents[x]]:
            parents[x] = parents[parents[x]]
            x = parents[x]
            indVal = self._indices[x]
        return x

    def merge(self, x: Tile, y: Tile) -> bool:
        """Merge the subsets of `x` and `y`.

        The smaller subset (the child) is merged into the larger subset (the
        parent). If the subsets are of equal size, the root element which was
        first inserted into the disjoint set is selected as the parent.

        Parameters
        ----------
        x, y : hashable object
            Elements to merge.

        Returns
        -------
        merged : bool
            True if `x` and `y` were in disjoint sets, False otherwise.
        """
        xr = self[x]
        yr = self[y]
        if self._indices[xr] == self._indices[yr]:
            return False

        if (self._sizes[xr], self._indices[yr]) < (self._sizes[yr], self._indices[xr]):
            xr, yr = yr, xr
        self._parents[yr] = xr
        self._sizes[xr] += self._sizes[yr]
        xrVals = self._sums[xr]
        yrVals = self._sums[yr]
        for i in range(self._num_vals):
            xrVals[i] += yrVals[i]
        self._nbrs[xr], self._nbrs[yr] = self._nbrs[yr], self._nbrs[xr]
        self.n_subsets -= 1
        return True

    def connected(self, x: Tile, y: Tile):
        """Test whether `x` and `y` are in the same subset.

        Parameters
        ----------
        x, y : hashable object
            Elements to test.

        Returns
        -------
        result : bool
            True if `x` and `y` are in the same set, False otherwise.
        """
        return self._indices[self[x]] == self._indices[self[y]]

    def subset_with_values(self, x: Tile) -> typing.Tuple[typing.Set[Tile], typing.List[float]]:
        """Get the subset containing `x`.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        result : set
            Subset containing `x`.
        """

        result = [x]
        nxt = self._nbrs[x]
        while self._indices[nxt] != self._indices[x]:
            result.append(nxt)
            nxt = self._nbrs[nxt]

        return set(result), self._sums[self[x]]

        # result = {x}
        # nxt = self._nbrs[x]
        # while self._indices[nxt] != self._indices[x]:
        #     result.add(nxt)
        #     nxt = self._nbrs[nxt]
        # return result

    def subset_size(self, x: Tile):
        """Get the size of the subset containing `x`.

        Note that this method is faster than ``len(self.subset(x))`` because
        the size is directly read off an internal field, without the need to
        instantiate the full subset.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        result : int
            Size of the subset containing `x`.
        """
        return self._sizes[self[x]]

    def subset_values(self, x: Tile) -> typing.List[float]:
        """Get the values of the subset containing `x`.

        Note that this method is faster than ``len(self.subset(x))`` because
        the value is directly read off an internal field, without the need to
        instantiate the full subset.

        Parameters
        ----------
        x : hashable object
            Input element.

        Returns
        -------
        result : int
            Size of the subset containing `x`.
        """
        return self._sums[self[x]]

    def subsets(self) -> typing.List[typing.Set[Tile]]:
        """Get all the subsets in the disjoint set.

        Returns
        -------
        result : list
            Subsets in the disjoint set.
        """
        result = []
        visited = set()
        for x in self:
            if x in visited:
                continue

            xset, vals = self.subset_with_values(x)
            visited.update(xset)
            result.append(xset)

        return result

    def subsets_with_values(self) -> typing.List[typing.Tuple[typing.Set[Tile], typing.List[float]]]:
        """Get all the subsets in the disjoint set.

        Returns
        -------
        result : list of (subset, subset sum) in the disjoint set.
        """
        result = []
        visited = set()
        for x in self:
            if x in visited:
                continue

            xset, vals = self.subset_with_values(x)
            visited.update(xset)
            result.append((xset, vals))

        return result

    def copy(self) -> FastDisjointTileSetMultiSum:
        copy = FastDisjointTileSetMultiSum(self._value_lookups)

        copy.n_subsets = self.n_subsets
        copy._sizes = self._sizes.copy()
        copy._sums = self._sums.copy()
        copy._parents = self._parents.copy()
        copy._nbrs = self._nbrs.copy()
        copy._indices = self._indices.copy()
        return copy
