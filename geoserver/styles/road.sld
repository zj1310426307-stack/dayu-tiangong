<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer><Name>road</Name><UserStyle><Name>road</Name><Title>Road</Title><FeatureTypeStyle>
    <Rule><MaxScaleDenominator>600000</MaxScaleDenominator><LineSymbolizer><Stroke><CssParameter name="stroke">#D8C68A</CssParameter><CssParameter name="stroke-width">1.4</CssParameter><CssParameter name="stroke-opacity">0.86</CssParameter></Stroke></LineSymbolizer></Rule>
    <Rule><MaxScaleDenominator>120000</MaxScaleDenominator><TextSymbolizer><Label><ogc:PropertyName>name</ogc:PropertyName></Label><Font><CssParameter name="font-family">Noto Sans CJK SC</CssParameter><CssParameter name="font-size">10</CssParameter></Font><LabelPlacement><LinePlacement/></LabelPlacement><Halo><Radius>1</Radius><Fill><CssParameter name="fill">#071923</CssParameter></Fill></Halo><Fill><CssParameter name="fill">#F4E3A4</CssParameter></Fill><VendorOption name="followLine">true</VendorOption><VendorOption name="conflictResolution">true</VendorOption></TextSymbolizer></Rule>
  </FeatureTypeStyle></UserStyle></NamedLayer>
</StyledLayerDescriptor>
