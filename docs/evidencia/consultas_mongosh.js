// Consultas equivalentes en mongosh, para capturas de pantalla de la sustentación.
// Uso:  docker exec -i <contenedor_mongo> mongosh upme_solar < docs/evidencia/consultas_mongosh.js
db = db.getSiblingDB("upme_solar");

print("== Índices de municipalities");
printjson(db.municipalities.getIndexes());

print("== Conteos");
print("municipios:", db.municipalities.countDocuments({}));
print("subregiones:", db.municipalities.distinct("pdet_subregion").length);

print("== Punto en polígono: ¿en qué municipio cae un punto interior de Apartadó?");
const m = db.municipalities.findOne({ name: /Apartad/ });
const pt = { type: "Point", coordinates: [-76.63, 7.88] };
printjson(db.municipalities.find({ geometry: { $geoIntersects: { $geometry: pt } } }, { name: 1 }).toArray());

print("== explain con índice (debe mostrar IXSCAN geometry_2dsphere)");
printjson(db.municipalities.find({ geometry: { $geoIntersects: { $geometry: pt } } })
  .explain("executionStats").executionStats);

print("== explain sin índice (COLLSCAN)");
printjson(db.municipalities.find({ geometry: { $geoIntersects: { $geometry: pt } } })
  .hint({ $natural: 1 }).explain("executionStats").executionStats);

print("== Vecinos de un municipio");
printjson(db.municipalities.find(
  { geometry: { $geoIntersects: { $geometry: m.geometry } } }, { name: 1 }).toArray());

print("== Municipios por subregión");
printjson(db.municipalities.aggregate([
  { $group: { _id: "$pdet_subregion", n: { $sum: 1 } } }, { $sort: { _id: 1 } }]).toArray());
