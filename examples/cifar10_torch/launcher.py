# Copyright 2021 DeepMind Technologies Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
r"""XManager launcher for CIFAR10.

Usage:

xmanager launch examples/cifar10_torch/launcher.py -- \
  --xm_wrap_late_bindings [--image_path=gcr.io/path/to/image/tag]
"""

import itertools

from absl import app
from absl import flags
from xmanager import xm
from xmanager import xm_local
from xmanager.cloud import utils

FLAGS = flags.FLAGS
flags.DEFINE_string('image_path', None, 'Image path.')

flags.DEFINE_integer('nodes', 1, 'Number of nodes.')
flags.DEFINE_integer('gpus_per_node', 2, 'Number of GPUs per node.')


@xm.run_in_asyncio_loop
async def main(_):
  async with xm_local.create_experiment(
      experiment_title='cifar10'
  ) as experiment:
    if FLAGS.image_path:
      spec = xm.Container(image_path=FLAGS.image_path)
    else:
      spec = xm.PythonContainer(
          # Package the current directory that this script is in.
          path='.',
          base_image='gcr.io/deeplearning-platform-release/pytorch-gpu.1-12',
          entrypoint=xm.ModuleName('cifar10'),
      )

    [executable] = experiment.package(
        [
            xm.Packageable(
                executable_spec=spec,
                executor_spec=xm_local.Vertex.Spec(),
                args={
                    # TODO: replace workerpool0 with the actual
                    # name of the job when Vertex AI supports custom name worker
                    # pools.
                    'master_addr_port': xm.ShellSafeArg(
                        utils.get_workerpool_address('workerpool0')
                    ),
                },
            ),
        ]
    )

    batch_sizes = [64, 1024]
    learning_rates = [0.1, 0.001]
    trials = list(
        dict([('batch_size', bs), ('learning_rate', lr)])
        for (bs, lr) in itertools.product(batch_sizes, learning_rates)
    )

    work_units = []
    for hyperparameters in trials:
      job_group = xm.JobGroup()
      for i in range(FLAGS.nodes):
        hyperparameters = dict(hyperparameters)
        hyperparameters['world_size'] = FLAGS.nodes
        hyperparameters['rank'] = i
        job_group.jobs[f'node_{i}'] = xm.Job(
            executable=executable,
            executor=xm_local.Vertex(
                xm.JobRequirements(t4=FLAGS.gpus_per_node)
            ),
            args=hyperparameters,
        )
      work_units.append(await experiment.add(job_group))
    print('Waiting for async launches to return values...')
  for work_unit in work_units:
    await work_unit.wait_until_complete()
  print('Experiment completed.')


if __name__ == '__main__':
  app.run(main)
