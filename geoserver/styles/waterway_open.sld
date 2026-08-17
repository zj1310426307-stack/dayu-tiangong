<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer><Name>waterway_open</Name><UserStyle><Name>waterway_open</Name><Title>广东主要水系中文标注</Title><FeatureTypeStyle>
    <Rule><LineSymbolizer><Stroke><CssParameter name="stroke">#42BFFF</CssParameter><CssParameter name="stroke-width">1.5</CssParameter><CssParameter name="stroke-opacity">0.92</CssParameter></Stroke></LineSymbolizer></Rule>
    <Rule><MaxScaleDenominator>350000</MaxScaleDenominator><TextSymbolizer><Label><ogc:PropertyName>name_zh</ogc:PropertyName></Label><Font><CssParameter name="font-family">Noto Sans CJK SC</CssParameter><CssParameter name="font-size">9</CssParameter></Font><LabelPlacement><LinePlacement/></LabelPlacement><Halo><Radius>1</Radius><Fill><CssParameter name="fill">#071923</CssParameter></Fill></Halo><Fill><CssParameter name="fill">#8DDEFF</CssParameter></Fill><VendorOption name="followLine">true</VendorOption><VendorOption name="conflictResolution">true</VendorOption></TextSymbolizer></Rule>
  </FeatureTypeStyle></UserStyle></NamedLayer>
</StyledLayerDescriptor>
