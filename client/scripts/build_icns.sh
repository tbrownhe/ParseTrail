NAME=parsetrail
ICON_BASE=parsetrail_1024px.png

cd ../assets/
mkdir $NAME.iconset

# Convert base 1024px image to multiple resolutions
sips -z 16 16 $ICON_BASE --out $NAME.iconset/icon_16x16.png
sips -z 32 32 $ICON_BASE --out $NAME.iconset/icon_16x16@2x.png

sips -z 32 32 $ICON_BASE --out $NAME.iconset/icon_32x32.png
sips -z 64 64 $ICON_BASE --out $NAME.iconset/icon_32x32@2x.png

sips -z 128 128 $ICON_BASE --out $NAME.iconset/icon_128x128.png
sips -z 256 256 $ICON_BASE --out $NAME.iconset/icon_128x128@2x.png

sips -z 256 256 $ICON_BASE --out $NAME.iconset/icon_256x256.png
sips -z 512 512 $ICON_BASE --out $NAME.iconset/icon_256x256@2x.png

sips -z 512 512 $ICON_BASE --out $NAME.iconset/icon_512x512.png
cp $ICON_BASE $NAME.iconset/icon_512x512@2x.png

# Convert to iconset
iconutil -c icns $NAME.iconset

# Delete intermediate
rm -R $NAME.iconset
