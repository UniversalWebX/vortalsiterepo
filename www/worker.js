// www.vortal.space -> vortal.space. Keeps the path and query, so a typed or old link
// like www.vortal.space/donutduck lands on the same page of the real site.
export default {
  fetch(request) {
    const url = new URL(request.url);
    url.protocol = 'https:';
    url.hostname = 'vortal.space';
    url.port = '';
    return Response.redirect(url.toString(), 301);
  }
};
