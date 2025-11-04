"""
Mini-Transformer Tabulaire Vivant avec Trace et Visualisation ASCII
-------------------------------------------------------------------
Chaque étape du calcul est matérialisée par un DataFrame Pandas.
Aucune donnée n'est conservée hors table.
Chaque transition laisse un stigmate (variation vectorielle).
Une visualisation ASCII montre les intensités de transformation.
"""

import numpy as np
import pandas as pd

# -----------------------------------------------------
# 0. Config générale
# -----------------------------------------------------
np.set_printoptions(precision=3, suppress=True)
d_model = 4
vocab = ["the", "cat", "sat"]
tokens = ["the", "cat", "sat"]
rng = np.random.default_rng(42)

# -----------------------------------------------------
# 1. Fonction de traçabilité (stigmates)
# -----------------------------------------------------
trace = []

def log_state(name, before, after):
    """Mesure la variation de norme entre deux tables et l'enregistre"""
    diff = after.to_numpy() - before.to_numpy()
    delta_norm = np.sqrt((diff ** 2).sum(axis=1))
    df_log = pd.DataFrame({
        "étape": name,
        "token": before.index,
        "delta_norm": delta_norm
    })
    trace.append(df_log)

# -----------------------------------------------------
# 2. Embeddings : table d'entrée
# -----------------------------------------------------
embedding_matrix = pd.DataFrame(
    rng.normal(0, 0.5, size=(len(vocab), d_model)),
    index=vocab,
    columns=[f"dim_{i}" for i in range(d_model)]
)

embeddings = pd.DataFrame(
    [embedding_matrix.loc[t] for t in tokens],
    index=tokens
)

print("\n=== EMBEDDINGS ===")
print(embeddings)

# -----------------------------------------------------
# 3. Q, K, V
# -----------------------------------------------------
def linear(df_in: pd.DataFrame, W: np.ndarray, prefix: str) -> pd.DataFrame:
    data = df_in.to_numpy().dot(W)
    return pd.DataFrame(data, index=df_in.index,
                        columns=[f"{prefix}_{i}" for i in range(W.shape[1])])

Wq = pd.DataFrame(rng.normal(0, 0.3, size=(d_model, d_model)),
                  columns=[f"q{i}" for i in range(d_model)])
Wk = pd.DataFrame(rng.normal(0, 0.3, size=(d_model, d_model)),
                  columns=[f"k{i}" for i in range(d_model)])
Wv = pd.DataFrame(rng.normal(0, 0.3, size=(d_model, d_model)),
                  columns=[f"v{i}" for i in range(d_model)])

print("\n=== POIDS Q ===\n", Wq)
print("\n=== POIDS K ===\n", Wk)
print("\n=== POIDS V ===\n", Wv)

Q = linear(embeddings, Wq.to_numpy(), "q")
K = linear(embeddings, Wk.to_numpy(), "k")
V = linear(embeddings, Wv.to_numpy(), "v")

log_state("Embeddings → Q", embeddings, Q)
log_state("Embeddings → K", embeddings, K)
log_state("Embeddings → V", embeddings, V)

print("\n=== TABLE Q ==="); print(Q)
print("\n=== TABLE K ==="); print(K)
print("\n=== TABLE V ==="); print(V)

# -----------------------------------------------------
# 4. Attention
# -----------------------------------------------------
scores = pd.DataFrame(Q.to_numpy().dot(K.to_numpy().T) / np.sqrt(d_model),
                      index=tokens, columns=tokens)
exp_scores = np.exp(scores - scores.max(axis=1).to_numpy()[:, None])
attn = exp_scores / exp_scores.sum(axis=1).to_numpy()[:, None]
attn = pd.DataFrame(attn, index=tokens, columns=tokens)

if scores.shape == attn.shape:
    log_state("Scores → Attention", scores, attn)

attn_out = pd.DataFrame(attn.to_numpy().dot(V.to_numpy()),
                        index=tokens,
                        columns=[f"attn_{i}" for i in range(d_model)])
log_state("Attention → Sortie", V, attn_out)

print("\n=== ATTENTION ===")
print(attn)
print("\n=== SORTIE ATTENTION ===")
print(attn_out)

# -----------------------------------------------------
# 5. Feed-Forward
# -----------------------------------------------------
W_ff = pd.DataFrame(rng.normal(0, 0.2, size=(d_model, d_model)),
                    columns=[f"ff{i}" for i in range(d_model)])
b_ff = pd.Series(rng.normal(0, 0.01, size=(d_model,)), index=[f"ff{i}" for i in range(d_model)])

ff = pd.DataFrame(attn_out.to_numpy().dot(W_ff.to_numpy()) + b_ff.to_numpy(),
                  index=tokens, columns=[f"ff_{i}" for i in range(d_model)])
log_state("Sortie_Attention → FeedForward", attn_out, ff)

print("\n=== FEED-FORWARD ===")
print(ff)

# -----------------------------------------------------
# 6. Trace des transformations
# -----------------------------------------------------
trace_df = pd.concat(trace, ignore_index=True)
print("\n=== TRACE DES STIGMATES ===")
print(trace_df)

# -----------------------------------------------------
# 7. Visualisation ASCII du flux latent
# -----------------------------------------------------
def render_bar(value, max_len=30):
    """Barre ASCII proportionnelle à l'intensité"""
    scaled = min(int(value * 10), max_len)
    return "█" * scaled + "·" * (max_len - scaled)

print("\n=== VISUALISATION ASCII DU FLUX LATENT ===")
for token in tokens:
    sub = trace_df[trace_df["token"] == token]
    line = f"{token:>4} | "
    for _, row in sub.iterrows():
        bar = render_bar(row["delta_norm"])
        line += f"{row['étape'][:10]:<12} {bar} {row['delta_norm']:.3f}\n       | "
    print(line[:-8])  # trim trailing pipe

# -----------------------------------------------------
# 8. Export
# -----------------------------------------------------
with pd.ExcelWriter("transformer_tabulaire_trace_ascii.xlsx") as writer:
    embeddings.to_excel(writer, sheet_name="embeddings")
    Q.to_excel(writer, sheet_name="Q")
    K.to_excel(writer, sheet_name="K")
    V.to_excel(writer, sheet_name="V")
    scores.to_excel(writer, sheet_name="scores")
    attn.to_excel(writer, sheet_name="attention")
    attn_out.to_excel(writer, sheet_name="attn_output")
    ff.to_excel(writer, sheet_name="feedforward")
    trace_df.to_excel(writer, sheet_name="trace")

print("\n💾 Toutes les tables et la visualisation des stigmates ont été enregistrées dans 'transformer_tabulaire_trace_ascii.xlsx'")
