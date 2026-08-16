import styles from "./Rail.module.css";

type Props = {
  total: number;
  conseguidos: number;
  invertidoUsd: number;
};

export function Rail({ total, conseguidos, invertidoUsd }: Props) {
  const porcentaje = total === 0 ? 0 : Math.round((conseguidos / total) * 100);

  return (
    <aside className={styles.rail}>
      <header className={styles.brand}>
        <span className={styles.lens} aria-hidden="true" />
        <h1 className={styles.title}>
          Pokédex
          <br />
          viviente
        </h1>
      </header>

      <section className={styles.counter}>
        <p className={styles.count}>
          <span className={styles.have}>{String(conseguidos).padStart(3, "0")}</span>
          <span className={styles.of}>/{total}</span>
        </p>
        <div className={styles.bar}>
          <span className={styles.fill} style={{ inlineSize: `${porcentaje}%` }} />
        </div>
        <p className={styles.hint}>
          Te faltan {total - conseguidos} de los 151 originales.
        </p>
      </section>

      <section className={styles.money}>
        <p className={styles.moneyLabel}>Invertido</p>
        <p className={styles.moneyValue}>
          ${invertidoUsd.toFixed(2)} <span className={styles.usd}>USD</span>
        </p>
      </section>
    </aside>
  );
}
