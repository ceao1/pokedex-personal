import type { NextConfig } from "next";

// El servidor de desarrollo bloquea por defecto las peticiones a sus propios
// recursos (`/_next/...`) que no vengan de localhost. Al abrir la app desde el
// celular por la IP de la red local, el HTML llega y el CSS se aplica, pero los
// chunks de JavaScript quedan bloqueados: la página nunca hidrata y ningún
// botón responde. Se ve como una app rota, no como un error.
//
// El caso de uso principal de este proyecto es justamente el celular, así que
// las IPs privadas están permitidas. `NEXT_DEV_ORIGIN` deja añadir una más sin
// tocar el archivo cuando el router reparte otra IP.
const origenesDeDesarrollo = [
  "192.168.*.*",
  "10.*.*.*",
  "172.16.*.*",
  ...(process.env.NEXT_DEV_ORIGIN ? [process.env.NEXT_DEV_ORIGIN] : []),
];

const nextConfig: NextConfig = {
  allowedDevOrigins: origenesDeDesarrollo,
};

export default nextConfig;
