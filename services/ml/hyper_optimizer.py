import lightgbm as lgb
import numpy as np
import optuna
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import TimeSeriesSplit


class HyperOptimizer:
    def __init__(self, n_trials=20):
        self.n_trials = n_trials

    def optimize(self, X_train, y_train, feature_names):
        # TimeSeriesSplit for strict out-of-sample temporal cross validation inside training set
        tscv = TimeSeriesSplit(n_splits=3)

        def objective(trial):
            param = {
                "objective": "regression",
                "metric": "rmse",
                "verbosity": -1,
                "boosting_type": "gbdt",
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
                "num_leaves": trial.suggest_int("num_leaves", 7, 31),
                "max_depth": trial.suggest_int("max_depth", 2, 5),
                "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
                "min_child_samples": trial.suggest_int("min_child_samples", 5, 30),
            }

            scores = []
            # Split train data chronologically
            for train_idx, val_idx in tscv.split(X_train):
                X_t, X_v = X_train[train_idx], X_train[val_idx]
                y_t, y_v = y_train[train_idx], y_train[val_idx]

                ds_train = lgb.Dataset(X_t, label=y_t, feature_name=feature_names)
                ds_val = lgb.Dataset(X_v, label=y_v, reference=ds_train, feature_name=feature_names)

                # We use early stopping on the inner validation set
                gbm = lgb.train(
                    param,
                    ds_train,
                    num_boost_round=100,
                    valid_sets=[ds_val],
                    callbacks=[lgb.early_stopping(stopping_rounds=10, verbose=False)],
                )

                preds = gbm.predict(X_v)
                rmse = np.sqrt(mean_squared_error(y_v, preds))
                scores.append(rmse)

            # Objective is to minimize average RMSE across chronological folds
            return np.mean(scores)

        study = optuna.create_study(direction="minimize")
        # Turn off optuna logs to keep stdout clean
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study.optimize(objective, n_trials=self.n_trials)

        best_params = study.best_params
        best_params["objective"] = "regression"
        best_params["metric"] = "rmse"
        best_params["verbosity"] = -1
        best_params["n_jobs"] = -1

        return best_params
