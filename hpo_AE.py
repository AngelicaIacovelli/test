import torch
import ray
from ray import train, tune
from ray.train import Checkpoint
from ray.tune.search.optuna import OptunaSearch
import hydra
from omegaconf import DictConfig
from train_AE import do_training
import os
from modulus.distributed.manager import DistributedManager

# initialize distributed manager
DistributedManager.initialize()
dist = DistributedManager()

def objective(config, cfg):  
    cfg.checkpoints.ckpt_path = os.getcwd() + "/" + cfg.checkpoints.ckpt_path 
    
    cfg.scheduler.lr = config["lr"] 
    cfg.scheduler.lr_decay = config["lr_decay"]
    cfg.training.batch_size = config["batch_size"]
    cfg.architecture.latent_size_gnn = config["latent_size_gnn"]
    cfg.architecture.latent_size_mlp = config["latent_size_mlp"]
    cfg.architecture.number_hidden_layers_mlp = config["number_hidden_layers_mlp"]
    cfg.architecture.process_iterations = config["process_iterations"]
    cfg.architecture.latent_size_AE = config["latent_size_AE"]

    metric = do_training(cfg, dist).cpu().detach().numpy()
    
    train.report({"Loss": float(metric)})  # Report to Tune

@hydra.main(version_base=None, config_path=".", config_name="config")
def main(cfg: DictConfig):

    cfg.work_directory = os.getcwd()
    cfg.training.output_interval = cfg.training.epochs - 1 

    search_space = {
        "lr": tune.loguniform(1e-4, 1e-1),
        "lr_decay": tune.loguniform(1e-3, 1e-1),
        "batch_size": tune.randint(10, 50), 
        "latent_size_gnn": tune.randint(1, 64),
        "latent_size_mlp": tune.randint(1, 200),
        "number_hidden_layers_mlp": tune.randint(1, 3),
        "process_iterations": tune.randint(0, 4),
        "latent_size_AE": tune.randint(1,100),
    }
    algo = OptunaSearch()  

    def objective_cfg(config):

        return objective(config, cfg)

    objective_with_gpu = tune.with_resources(objective_cfg, {"gpu": 1})

    storage_path = os.path.expanduser("/home/aiacovelli/ray_results")
    exp_name = "hpo_AE"
    path = os.path.join(storage_path, exp_name)

    if tune.Tuner.can_restore(path):
        tuner = tune.Tuner.restore(
            path, 
            trainable = objective_with_gpu, 
            param_space=search_space,
            resume_errored=True
        )
    else:
        tuner = tune.Tuner(  
            trainable = objective_with_gpu,
            tune_config=tune.TuneConfig(
                metric="Loss", 
                mode="min", 
                search_alg=algo,
                num_samples=cfg.hyperparameter_optimization.runs
            ),
            run_config=train.RunConfig(storage_path=storage_path, name=exp_name),
            param_space=search_space,
        )
    
    results = tuner.fit()
    print("Best config is:", results.get_best_result().config)

if __name__ == "__main__":
    main()
