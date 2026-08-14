<?xml version="1.0" encoding="UTF-8"?>
<qgis version="3.44.0-Solothurn" styleCategories="Symbology|Labeling">
  <renderer-v2 type="categorizedSymbol" attr="quality_status" symbollevels="0" enableorderby="0">
    <categories><category value="pending" label="待质检" symbol="0"/><category value="passed" label="已通过" symbol="1"/><category value="failed" label="未通过" symbol="2"/></categories>
    <symbols>
      <symbol name="0" type="marker"><layer class="SimpleMarker"><Option type="Map"><Option name="name" value="triangle"/><Option name="color" value="245,166,35,255"/><Option name="outline_color" value="55,55,55,255"/><Option name="size" value="3.8"/><Option name="size_unit" value="MM"/></Option></layer></symbol>
      <symbol name="1" type="marker"><layer class="SimpleMarker"><Option type="Map"><Option name="name" value="triangle"/><Option name="color" value="39,174,96,255"/><Option name="outline_color" value="55,55,55,255"/><Option name="size" value="3.8"/><Option name="size_unit" value="MM"/></Option></layer></symbol>
      <symbol name="2" type="marker"><layer class="SimpleMarker"><Option type="Map"><Option name="name" value="triangle"/><Option name="color" value="220,53,69,255"/><Option name="outline_color" value="55,55,55,255"/><Option name="size" value="4.2"/><Option name="size_unit" value="MM"/></Option></layer></symbol>
    </symbols>
  </renderer-v2>
  <labeling type="simple"><settings><text-style fieldName="coalesce(&quot;name&quot;,&quot;pump_code&quot;)" isExpression="1" fontFamily="Noto Sans CJK SC" fontSize="8"/><placement placement="0" dist="1.5"/></settings></labeling>
</qgis>
