# Licensed under a 3-clause BSD style license - see LICENSE.rst

"""Control a pipeline, execution flow and configurations.

The basic design is:
    - The Processor manages all the inputs, configs and the running;
    - Processor has a ProductManager instance, that store all Products;
    - Processor has a lot of Stages, that get a Config, a Instrument and
      a Product and process it;
    - Stages modify one product per time;
    - Stage can have Stage children, Config can have Config children. In the
      same logic;
    - All these things are objects that can be frozen for run.
"""

# TODO: implement logging


__all__ = ['Product', 'ProductManager', 'Config', 'Stage', 'Instrument',
           'Processor']


class Config:
    """Store the config of a stage."""
    frozen = False
    def __init__(self, **kwargs):
        for name, value in kwargs.items():
            self.__dict__[name] = value

    def __getattribute__(self, name):
        if name in self.__dict__.keys():
            return object.__getattribute__(self, name)
        else:
            # TODO: think if it is better to return None or raise error
            return None

    def __setattr__(self, name, value):
        if not self.frozen:
            self.__dict__[name] = value


class Product:
    """Store all informations and data of a product."""
    # TODO: inherite Config?
    def __init__(self, product_manager, raw_files=[], ccddata=None, **kwargs):
        self.product_manager = product_manager
        self.raw_files = []
        self.ccddata = ccddata

        for name, value in kwargs.items():
            self.__dict__[name] = value

    def __getattribute__(self, name):
        if name in self.__dict__.keys():
            return object.__getattribute__(self, name)
        else:
            # TODO: think if it is better to return None or raise error
            return None

    def __setattr__(self, name, value):
        # Products have to be changed, so, don't freeze
        self.__dict__[name] = value


class Instrument:
    """Store all the informations and needed functions of a instrument."""
    frozen = False
    # TODO: I know it is almost equal Config, think if it is better to
    # inherite Config or keep separated
    def __init__(self, **kwargs):
        for name, value in kwargs.items():
            self.__dict__[name] = value

    def __getattribute__(self, name):
        if name in self.__dict__.keys():
            return object.__getattribute__(self, name)
        else:
            # TODO: think if it is better to return None or raise error
            return None

    def __setattr__(self, name, value):
        if not self.frozen:
            self.__dict__[name] = value


class ProductManager:
    """Manage a bunch of products."""
    def __init__(self, processor):
        self.processor = processor
        self.products = []
        self.iterating = False

    @property
    def number_of_products(self):
        return len(self.products)

    def add_product(self, product, index=None):
        """Add a product to the manager."""
        if product in self.products:
            raise ValueError('Product already in the manager.')
        else:
            if self.iterating:
                raise RuntimeError('Insert product in index while iteratin'
                                    'g not allowed.')
            elif index is not None:
                self.products.insert(index, product)
            else:
                self.products.append(product)

    def del_product(self, product):
        """Delete a product from the manager."""
        self.products.remove(product)

    def iterate_products(self):
        """Iterate over all products."""
        if self.number_of_products == 0:
            raise ValueError('No products available in this product manager.')

        i = 0
        self.iterating = True
        while i < self.number_of_products:
            yield self.products[i]
            i += 1

        self.iterating = False

    def product(self, index):
        """Get one specific product."""
        return self.products[index]


class Stage:
    """Stage process (sub-part) of a pipeline."""
    config = Config()
    _children = []
    processor = None
    parent = None
    name = None

    def processor(self, processor):
        self.processor = processor

    def add_children(self, name, stage):
        """Add a children stage to this stage."""
        if stage not in self._children:
            self._children.append(stage)
            stage.parent = self
            stage.name = name

    def remove_children(self, stage):
        """Remove a children stage from this stage."""
        self._children.remove(stage)
        stage.parent = None

    def run(self, product, config=None, instrument=None):
        """Run the stage"""
        raise NotImplementedError('Stage not implemented.')

    def _run_children(self, product, config=None, instrument=None):
        for i in self._children:
            conf = config.get(i.name, None)
            i(product, conf, instrument)

    def __call__(self, product, config=None, instrument=None):
        self.run(product, config, instrument)
        self._run_children(product, config, instrument)


class Processor:
    """Master class of a pipeline"""
    def __init__(self, config_file=None):
        self.prod_manager = ProductManager(self)
        self.instrument = None
        self.config_dict = {}
        self._stages = []
        self._processing_stage = None
        self.running = False

    @property
    def number_of_stages(self):
        return len(self._stages)

    def setup(self):
        """Set a special stage that populate the ProductManager.

        This function also can handle other things before properly run the
        pipeline.
        """
        raise NotImplementedError('setup is not implementated to this pipeline.'
                                  ' Required.')

    @property
    def processing_index(self):
        return self._processing_stage

    def set_current_stage(self, index):
        """Set the index of processing, useful for loops iteration loops."""
        if not self.running:
            raise ValueError('Current stage set only available when pipeline '
                             'is running.')
        self._processing_stage = index

    def add_stage(self, name, stage, index=None):
        """Add a stage to the pipeline."""
        if name in self._stages[:][0]:
            raise ValueError('Stage {} already in the pipeline.'.format(name))
        elif self.running:
            raise RuntimeError('Pipeline running, cannot add stages.')
        elif not isinstance(stage, Stage):
            raise ValueError('Not a valid Stage.')
        elif index is not None:
            self._stages.insert(index, (name, stage))
        else:
            self._stages.append((name, stage))

    def remove_stage(self, name):
        """Remove a stage from the pipeline."""
        if self.running:
            raise RuntimeError('Pipeline running, cannot remove stages.')
        index = self.get_index(name)
        self._stages.pop(index)

    def get_index(self, name):
        """Get the index of a stage."""
        for i in self.number_of_stages:
            if self._stages[i][0] == name:
                return i
        return None

    def run(self, **runargs):
        """Run the pipeline."""
        if self.number_of_stages == 0:
            raise ValueError('This pipeline has no stages.')
        if self.prod_manager.number_of_products == 0:
            raise ValueError('This pipeline has no products.')

        self.running = True
        for prod in self.prod_manager.products:
            self._processing_stage = 0
            # Allow stages to set the current processing stage, like for iterating
            while self._processing_stage < self.number_of_stages:
                stage_name, stage = self._stages[self._processing_stage]
                self._processing_stage += 1
                if stage_name in self.config.keys():
                    config = self.config[stage_name]
                else:
                    config = None
                stage(prod, config, instrument=self.instrument)
        self.running = False
        self._processing_stage = None
